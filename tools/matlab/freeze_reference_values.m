function freeze_reference_values()
%FREEZE_REFERENCE_VALUES  Capture MATLAB golden outputs for the Python port.
%   Runs the fermi-viewer (MATLAB) parsers + analysis on the test corpus and
%   deterministic reference cases, writing JSON goldens into
%   fermiviewer/tests/golden/. The Python port verifies against these in CI
%   with no MATLAB dependency (PORT_PLAN.md item 3).
%
%   Run from anywhere; locates ../fermi-viewer relative to this file:
%       run('tools/matlab/freeze_reference_values.m')
%
%   Domains captured in v1 (extend per-domain as port workstreams start):
%       manifest.json            — source commit, date, MATLAB release
%       parsers_committed.json   — committed Microscopy + BCF corpus
%       eels_realdata.json       — local-only EELS corpus (skipped if absent)
%       eds_tables.json          — k-factors, line energies, MAC, CL/ZAF refs
%       diffraction.json         — wavelengths, phase DB, simulate+index
%
%   Failed captures are reported and listed in manifest.skipped — fix the
%   call and re-run; never commit a golden produced from an error path.

    thisDir   = fileparts(mfilename('fullpath'));
    portRoot  = fileparts(fileparts(thisDir));            % fermiviewer/
    mlRoot    = fullfile(fileparts(portRoot), 'fermi-viewer');
    goldenDir = fullfile(portRoot, 'tests', 'golden');

    assert(isfolder(mlRoot), 'fermi-viewer not found at %s', mlRoot);
    if ~isfolder(goldenDir), mkdir(goldenDir); end
    addpath(mlRoot);

    skipped = {};

    % ── manifest ─────────────────────────────────────────────────────
    [~, commit] = system(sprintf('git -C "%s" rev-parse --short HEAD', mlRoot));
    manifest.sourceRepo    = 'fermi-viewer';
    manifest.sourceCommit  = strtrim(commit);
    manifest.matlabRelease = char(matlabRelease().Release);
    manifest.generated     = char(datetime('now', 'Format', 'yyyy-MM-dd HH:mm'));

    % ── parsers: committed corpus ────────────────────────────────────
    try
        writeGolden(goldenDir, 'parsers_committed.json', ...
            captureParsersCommitted(mlRoot));
    catch ME
        skipped{end+1} = sprintf('parsers_committed: %s', ME.message);
    end

    % ── EELS: local-only real corpus (skip-if-absent) ────────────────
    eelsDir = fullfile(mlRoot, '+test_datasets', 'EELS');
    if isfile(fullfile(eelsDir, 'FigS6_apatite_ZLP.dm4'))
        try
            writeGolden(goldenDir, 'eels_realdata.json', captureEELS(eelsDir));
        catch ME
            skipped{end+1} = sprintf('eels_realdata: %s', ME.message);
        end
    else
        skipped{end+1} = 'eels_realdata: local corpus absent (fetchRealEelsData)';
    end

    % ── EDS tables + reference quantification ────────────────────────
    try
        writeGolden(goldenDir, 'eds_tables.json', captureEDS());
    catch ME
        skipped{end+1} = sprintf('eds_tables: %s', ME.message);
    end

    % ── diffraction: wavelengths, phase DB, simulate + index ─────────
    try
        writeGolden(goldenDir, 'diffraction.json', captureDiffraction());
    catch ME
        skipped{end+1} = sprintf('diffraction: %s', ME.message);
    end

    % ── imaging: filter/segment fingerprints on closed-form synthetics ─
    try
        writeGolden(goldenDir, 'imaging.json', captureImaging());
    catch ME
        skipped{end+1} = sprintf('imaging: %s', ME.message);
    end

    manifest.skipped = skipped;
    writeGolden(goldenDir, 'manifest.json', manifest);

    fprintf('\nGolden capture complete → %s\n', goldenDir);
    if ~isempty(skipped)
        fprintf('SKIPPED (%d):\n', numel(skipped));
        fprintf('  - %s\n', skipped{:});
    end
end


% ════════════════════════════════════════════════════════════════════
function out = captureImaging()
    % Closed-form deterministic synthetics — defined identically in
    % tests/test_imaging.py (docs/w3_imaging_audit.md). 1-based r, c.
    [C, R] = meshgrid(1:96, 1:64);
    base  = sin(R/7) .* cos(C/11) + 0.001 * (R .* C) / (64*96);
    noisy = base + 0.05 * sin(13*R + 7*C);
    bw    = base > 0.2;

    out.synthetic.baseSum  = sum(base(:));
    out.synthetic.noisySum = sum(noisy(:));
    out.synthetic.bwCount  = nnz(bw);

    g = imaging.applyGaussian(base, Sigma=2);
    out.gaussian = fingerprint(g);

    m = imaging.applyMedian(noisy, WindowSize=5);
    out.median = fingerprint(m);

    u = imaging.unsharpMask(base, Sigma=2, Amount=1.5);
    out.unsharp = fingerprint(u);

    b = imaging.butterworthFilter(base, LowCutoff=0.05, HighCutoff=0.5, Order=2);
    out.butterworth = fingerprint(real(b));

    cl = imaging.clahe(base, TileSize=[8 8], ClipLimit=0.01, NumBins=256);
    out.clahe = fingerprint(cl);

    out.binAvg = fingerprint(imaging.binImage(base, BinSize=4, Mode='average'));
    out.binSum = fingerprint(imaging.binImage(base, BinSize=4, Mode='sum'));

    out.downsample = fingerprint(imaging.areaDownsample(base, 16, 24));
    out.thumbnail  = fingerprint(imaging.generateThumbnail(base, MaxSize=32));

    pl = imaging.planeLevel(noisy, Order=2);
    out.planeLevel.coeffs     = pl.coeffs(:)';
    out.planeLevel.leveledSum = sum(abs(pl.leveled(:)));

    out.percentiles = [imaging.percentile(base(:), 1), ...
                       imaging.percentile(base(:), 50), ...
                       imaging.percentile(base(:), 99)];

    mo = imaging.multiOtsu(base, NumClasses=3, NumBins=256);
    out.multiOtsu.thresholds = mo.thresholds(:)';

    ops = {'erode', 'dilate', 'open', 'close'};
    for k = 1:numel(ops)
        % morphOp validates mustBeNumeric — pass the mask as double 0/1
        r = imaging.morphOp(double(bw), ops{k}, Radius=2, Shape="disk");
        out.morph.(ops{k}) = nnz(r);
    end

    [L8, n8] = imaging.bwlabel(bw, 8);
    [~,  n4] = imaging.bwlabel(bw, 4);
    out.label.n8 = n8;
    out.label.n4 = n4;
    areas = accumarray(L8(L8 > 0), 1);
    out.label.areas8Sorted = sort(areas(:))';

    d34 = imaging.distanceTransform(bw, Metric="chamfer34");
    dcb = imaging.distanceTransform(bw, Metric="cityblock");
    out.distance.chamferSum = sum(d34(:));
    out.distance.chamferMax = max(d34(:));
    out.distance.cityblockSum = sum(dcb(isfinite(dcb)));

    % ── tranche 2 ────────────────────────────────────────────────────
    [Lw, nw] = imaging.watershed(bw, MinMarkerDistance=5);
    out.watershed.n = nw;
    areasW = accumarray(Lw(Lw > 0), 1);
    out.watershed.areasSorted = sort(areasW(:))';
    out.watershed.foreground = nnz(Lw > 0);

    [L8b, ~] = imaging.bwlabel(bw, 8);
    [parts, ~, nKept] = imaging.regionStats(L8b, base, ...
        MinArea=50, PixelSize=0.4);
    out.regions.nKept = nKept;
    out.regions.areas = [parts.area];
    out.regions.equivDiameters = [parts.equivDiameter];
    out.regions.meanIntensities = [parts.meanIntensity];
    cent = vertcat(parts.centroid);
    out.regions.centroidSum = sum(cent(:));
    out.regions.areaCalibratedSum = sum([parts.areaCalibrated]);

    st = imaging.structureTensor(base, Sigma=3, GradientSigma=1);
    out.structure.coherenceSum = sum(st.coherence(:));
    out.structure.energySum = sum(st.energy(:));
    out.structure.lambda1Sum = sum(st.lambda1(:));
    out.structure.orientPx = st.orientation(20, 30);

    ne1 = imaging.noiseEstimate(noisy, Method='mad');
    out.noise.sigmaMad = ne1.sigma;
    out.noise.snrDb = ne1.snr;
    out.noise.type = char(ne1.noiseType);
    ne2 = imaging.noiseEstimate(noisy, Method='localvar');
    out.noise.sigmaLocalVar = ne2.sigma;

    % NumBins=32 = floor(min(H,W)/2), the documented default — the
    % actual default (0) violates radialProfile's own mustBePositive
    % validator, so the no-arg call errors (latent MATLAB bug).
    [rad, avgP, maxP] = imaging.radialProfile(base, NumBins=32);
    out.radial.n = numel(rad);
    out.radial.radiiSum = sum(rad);
    out.radial.avgSum = sum(avgP(~isnan(avgP)));
    out.radial.maxSum = sum(maxP(~isnan(maxP)));
    out.radial.nanCount = nnz(isnan(avgP));

    [r1, i1] = imaging.azimuthalIntegrate(base);
    out.azimuthal.full.radiiSum = sum(r1);
    out.azimuthal.full.intensitySum = sum(i1(~isnan(i1)));
    out.azimuthal.full.n = numel(r1);
    [~, i2] = imaging.azimuthalIntegrate(base, SectorMin=300, SectorMax=60);
    out.azimuthal.wrap.intensitySum = sum(i2(~isnan(i2)));
    out.azimuthal.wrap.nanCount = nnz(isnan(i2));
end


function fp = fingerprint(img)
    % Scalar fingerprints for array equivalence at rel 1e-9.
    img = double(img);
    fp.size   = size(img);
    fp.sum    = sum(img(:));
    fp.sumAbs = sum(abs(img(:)));
    fp.px     = img(min(20, end), min(30, end));   % spot check
end


% ════════════════════════════════════════════════════════════════════
function out = captureParsersCommitted(mlRoot)
    micDir = fullfile(mlRoot, '+test_datasets', 'Microscopy');
    bcfDir = fullfile(mlRoot, '+test_datasets', 'BCF');

    files = [dir(fullfile(micDir, '*.dm3')); dir(fullfile(micDir, '*.dm4')); ...
             dir(fullfile(micDir, '*.mrc')); dir(fullfile(micDir, '*.ser')); ...
             dir(fullfile(micDir, '*.tif'))];
    images = struct([]);
    for k = 1:numel(files)
        f = fullfile(micDir, files(k).name);
        try
            d  = parser.importAuto(f);
            ps = d.metadata.parserSpecific;
            e.file = files(k).name;
            if isfield(ps, 'imageData') && ps.isImage
                px = double(ps.imageData.pixels);
                e.mode      = '2D';
                e.height    = ps.imageData.height;
                e.width     = ps.imageData.width;
                e.bitDepth  = ps.imageData.bitDepth;
                e.pixelSize = ps.imageData.pixelSize;
                e.pixelUnit = ps.imageData.pixelUnit;
                e.pixSum    = sum(px(:));
                e.pixMean   = mean(px(:));
                e.pixMin    = min(px(:));
                e.pixMax    = max(px(:));
            elseif isfield(ps, 'spectrumImage')
                si = ps.spectrumImage;
                e.mode       = '3D';
                e.Ny = si.Ny; e.Nx = si.Nx; e.nChannels = si.nChannels;
                e.energyFirst = si.energyAxis(1);
                e.energyLast  = si.energyAxis(end);
                e.energyScale = si.energyScale;
                e.cubeSum     = sum(double(si.cube(:)));
            else
                e.mode = '1D';
                e.nChannels = ps.spectrumData.nChannels;
                e.countsSum = sum(ps.spectrumData.counts);
            end
            images = [images; e]; clear e; %#ok<AGROW>
        catch ME
            fprintf('  ! parser skip %s: %s\n', files(k).name, ME.message);
        end
    end
    out.images = images;

    bcfs = dir(fullfile(bcfDir, '*.bcf'));
    bcfOut = struct([]);
    for k = 1:numel(bcfs)
        f = fullfile(bcfDir, bcfs(k).name);
        try
            ws = warning('off', 'all'); cw = onCleanup(@() warning(ws));
            d   = parser.importBCF(f);
            eds = d.metadata.parserSpecific.edsData;
            b.file       = bcfs(k).name;
            b.nChannels  = eds.nChannels;
            b.calibAbs   = eds.calibAbs;
            b.calibLin   = eds.calibLin;
            b.elements   = {eds.elements};
            b.sumSpectrumTotal = sum(double(eds.sumSpectrum));
            % Always present so the struct array concatenates (the real
            % Esprit map skips its 4.3 GB cube via MaxCubeBytes)
            b.cubeSize  = size(eds.cube);
            b.cubeClass = class(eds.cube);
            if ~isempty(eds.cube)
                b.cubeTotal = sum(double(eds.cube(:)));
            else
                b.cubeTotal = [];
            end
            bcfOut = [bcfOut; b]; clear b; %#ok<AGROW>
        catch ME
            fprintf('  ! bcf skip %s: %s\n', bcfs(k).name, ME.message);
        end
    end
    out.bcf = bcfOut;
end


% ════════════════════════════════════════════════════════════════════
function out = captureEELS(eelsDir)
    % ZLP file — calibration + thickness + alignment + KK
    d  = parser.importAuto(fullfile(eelsDir, 'FigS6_apatite_ZLP.dm4'));
    si = d.metadata.parserSpecific.spectrumImage;
    z.dims        = [si.Ny, si.Nx, si.nChannels];
    z.energyFirst = si.energyAxis(1);
    z.energyScale = si.energyScale;
    [~, pk] = max(si.sumSpectrum);
    z.zlpEnergy   = si.energyAxis(pk);
    z.sumTotal    = sum(si.sumSpectrum);
    [~, tol] = imaging.eels.eelsFourierLog(si.energyAxis, si.sumSpectrum);
    z.fourierLogTOverLambda = tol;
    [tMap, mask] = imaging.eels.eelsThicknessMap(si.cube, si.energyAxis);
    z.thicknessMapMedian = median(tMap(mask), 'omitnan');
    z.thicknessValidPx   = nnz(mask);
    [~, shifts] = imaging.eels.eelsAlignZLP(si.cube, si.energyAxis);
    z.alignMaxAbsShift = max(abs(shifts(:)));
    kk = imaging.eels.eelsKramersKronig(si.energyAxis, si.sumSpectrum, ...
        AccVoltage=200, CollectionAngle=10);
    z.kkThickness = kk.thickness;
    band = kk.energy > 8 & kk.energy < 30;
    z.kkEps2MedianPlasmon = median(kk.eps2(band));
    out.zlp = z;

    % O-K core-loss — background + map
    d  = parser.importAuto(fullfile(eelsDir, 'Fig4_apatite79221_OKedge_vesicle.dm4'));
    si = d.metadata.parserSpecific.spectrumImage;
    E = si.energyAxis; I = si.sumSpectrum;
    o.dims = [si.Ny, si.Nx, si.nChannels];
    o.energyFirst = E(1); o.energyLast = E(end);
    fitWin = [E(1) + 2, 524];
    [sig, ~, p] = imaging.eels.eelsBackground(E, I, FitWindow=fitWin);
    o.bgFitWindow = fitWin;
    o.bgPowerlawR = p.r;
    o.bgPowerlawA = p.A;
    post = E > 532 & E < 572;
    o.edgeFraction = sum(sig(post)) / sum(I(post));
    map = imaging.eels.eelsExtractMap(si.cube, E, [532, 572], BackgroundWindow=fitWin);
    o.mapSum = sum(map(:)); o.mapMax = max(map(:));
    res = imaging.eels.eelsSVD(si.cube, E, NumComponents=5);
    o.svdExplained = res.explained(1:3);
    out.okedge = o;

    % F-K / Fe-L23 — background on second window
    d  = parser.importAuto(fullfile(eelsDir, 'FigS4_apatite79221_F_Fe.dm4'));
    si = d.metadata.parserSpecific.spectrumImage;
    f.dims = [si.Ny, si.Nx, si.nChannels];
    [~, ~, p] = imaging.eels.eelsBackground(si.energyAxis, si.sumSpectrum, ...
        FitWindow=[si.energyAxis(1) + 2, 678]);
    f.bgPowerlawR = p.r;
    out.f_fe = f;

    % rosettasciio tiny SI — independent writer
    d  = parser.importAuto(fullfile(eelsDir, 'rosettasciio_EELS_SI.dm4'));
    si = d.metadata.parserSpecific.spectrumImage;
    r.dims = [si.Ny, si.Nx, si.nChannels];
    r.energyFirst = si.energyAxis(1);
    r.energyScale = si.energyScale;
    r.pixelSize   = si.pixelSize;
    r.cubeSum     = sum(double(si.cube(:)));
    out.rsciio = r;

    % Edge table (the data itself is a golden)
    edges = imaging.eels.eelsEdgeTable();
    out.edgeTable = struct('symbol', {{edges.symbol}}, ...
                           'onsetEV', [edges.onsetEV], 'Z', [edges.Z]);
end


% ════════════════════════════════════════════════════════════════════
function out = captureEDS()
    % edsKFactorTable returns a dictionary (not JSON-encodable) — flatten
    kTable = imaging.eds.edsKFactorTable();
    ks = keys(kTable);
    out.kFactorTable = struct('element', cellstr(ks), ...
                              'k', num2cell(kTable(ks)));

    % Line energies (default options) for a spread of Z
    syms = {'C','O','Si','Ti','Fe','Cu','Mo','Pb'};
    for k = 1:numel(syms)
        [e, lineUsed] = imaging.eds.lineEnergy(syms{k});
        le(k) = struct('symbol', syms{k}, 'keV', e, 'line', lineUsed); %#ok<AGROW>
    end
    out.lineEnergies = le;

    % Mass absorption coefficient samples
    pairs = {{'O','Fe'}, {'Si','O'}, {'Fe','Si'}, {'Cu','C'}};
    for k = 1:numel(pairs)
        mac(k) = struct('emitter', pairs{k}{1}, 'absorber', pairs{k}{2}, ...
            'mu_rho', imaging.eds.massAbsorptionCoeff(pairs{k}{1}, pairs{k}{2})); %#ok<AGROW>
    end
    out.massAbsorption = mac;

    % Cliff-Lorimer reference case: deterministic two-element maps
    [xg, yg] = ndgrid(0:7, 0:7);
    mapFe = 100 + xg + 10*yg;          % deterministic gradients
    mapO  = 50  + 2*xg + yg;
    cl = imaging.eds.cliffLorimer({mapFe, mapO}, {'Fe', 'O'});
    out.cliffLorimer_FeO = cl;

    % ZAF reference case (defaults)
    zaf = imaging.eds.zafCorrection({mapFe, mapO}, {'Fe', 'O'});
    out.zaf_FeO = zaf;
end


% ════════════════════════════════════════════════════════════════════
function out = captureDiffraction()
    kVs = [60, 80, 100, 200, 300];
    for k = 1:numel(kVs)
        wl(k) = struct('kV', kVs(k), ...
            'lambda', imaging.diffraction.calcElectronWavelength(kVs(k))); %#ok<AGROW>
    end
    out.wavelengths = wl;

    % Phase database — names + lattice constants are themselves goldens
    db = calc.crystal.phaseDatabase();
    out.phaseCount = numel(db);
    out.phases = arrayfun(@(p) struct('name', p.name), db);

    % Simulate Silicon [001] and capture the spot list.
    % Spot fields: hkl, dSpacing, intensity, pixelRow, pixelCol.
    sim = imaging.diffraction.simulateDiffraction('Silicon', ...
        ZoneAxis=[0 0 1], AccVoltage=200, ImageSize=[512 512]);
    s.phaseName = sim.phaseName;
    s.lambda    = sim.lambda;
    s.nSpots    = numel(sim.spots);
    s.imageSum  = sum(double(sim.image(:)));
    % Top-10 spots by intensity: hkl + d-spacing + position
    [~, order] = sort([sim.spots.intensity], 'descend');
    top = sim.spots(order(1:min(10, end)));
    s.topSpots = arrayfun(@(sp) struct('hkl', sp.hkl, ...
        'dSpacing', sp.dSpacing, 'intensity', sp.intensity, ...
        'pixelRow', sp.pixelRow, 'pixelCol', sp.pixelCol), top);
    out.simulateSilicon001 = s;

    % Round-trip: index the simulated pattern's spots (x = col, y = row)
    if ~isempty(sim.spots)
        pos = [[sim.spots.pixelCol]', [sim.spots.pixelRow]'];
        idx = imaging.diffraction.indexDiffraction(pos, [512 512], ...
            AccVoltage=200);
        r.fields = fieldnames(idx);
        if isfield(idx, 'matches') && ~isempty(idx.matches)
            r.topPhase = idx.matches(1).phase;
            r.topScore = idx.matches(1).score;
        end
        out.indexRoundTrip = r;
    end
end


% ════════════════════════════════════════════════════════════════════
function writeGolden(goldenDir, name, data)
    txt = jsonencode(data, 'PrettyPrint', true);
    fid = fopen(fullfile(goldenDir, name), 'w');
    assert(fid ~= -1, 'cannot write %s', name);
    fwrite(fid, txt);
    fclose(fid);
    fprintf('  ✔ %s\n', name);
end
