// WebGL image renderer (handoff §13 render path): raw 16-bit intensities
// on the GPU with window/level/gamma/colormap applied in the fragment
// shader — instant contrast at any size, no PNG round-trips.
//
// The 16-bit value is packed into the R (high) and G (low) bytes of an
// RGBA8 texture. v = 256·hi + lo is linear in both bytes, so fixed-
// function LINEAR filtering interpolates it exactly — no float-texture
// extensions, works on WebGL1.

import type { View } from "../store/viewer";
import type { Size } from "../lib/geometry";

const VERT = `
attribute vec2 a_pos;          // image-pixel corners of the quad
uniform vec2 u_imgSize;
uniform vec2 u_vpSize;         // CSS px
uniform vec3 u_view;           // z, px, py
varying vec2 v_uv;
void main() {
  v_uv = a_pos / u_imgSize;
  vec2 screen = (a_pos - u_view.yz * u_imgSize) * u_view.x + u_vpSize * 0.5;
  vec2 clip = screen / u_vpSize * 2.0 - 1.0;
  gl_Position = vec4(clip.x, -clip.y, 0.0, 1.0);
}`;

const FRAG = `
// highp is mandatory in vertex shaders but OPTIONAL in fragment shaders
// (GLSL ES 1.00 §4.5.3). Declare it only where supported so the shader
// still compiles on mediump-only GPUs; the 16-bit unpack below wants the
// extra mantissa, so prefer highp whenever the driver advertises it.
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
uniform sampler2D u_tex;       // packed 16-bit: R=hi byte, G=lo byte
uniform sampler2D u_lut;       // 256×1 colormap
uniform vec4 u_window;         // lo, hi, gamma, invert — normalized units
varying vec2 v_uv;
void main() {
  vec4 p = texture2D(u_tex, v_uv);
  float v = (p.r * 255.0 * 256.0 + p.g * 255.0) / 65535.0;
  float t = clamp((v - u_window.x) / max(u_window.y - u_window.x, 1e-6), 0.0, 1.0);
  t = pow(t, 1.0 / max(u_window.z, 1e-3));
  t = mix(t, 1.0 - t, u_window.w);
  gl_FragColor = texture2D(u_lut, vec2(t, 0.5));
}`;

export interface Window16 {
  lo: number; // normalized [0,1] against the image min/max
  hi: number;
  gamma: number;
  invert?: boolean;
}

export class GLRenderer {
  private gl: WebGLRenderingContext;
  private prog: WebGLProgram;
  private tex: WebGLTexture | null = null;
  private lut: WebGLTexture | null = null;
  private imgSize: Size = { w: 0, h: 0 };

  constructor(private canvas: HTMLCanvasElement) {
    const gl = canvas.getContext("webgl", { premultipliedAlpha: false });
    if (!gl) throw new Error("WebGL unavailable");
    this.gl = gl;
    this.prog = this.compile();

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    const loc = gl.getAttribLocation(this.prog, "a_pos");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

    gl.uniform1i(this.u("u_tex"), 0);
    gl.uniform1i(this.u("u_lut"), 1);
  }

  private u(name: string): WebGLUniformLocation | null {
    return this.gl.getUniformLocation(this.prog, name);
  }

  private compile(): WebGLProgram {
    const { gl } = this;
    const mk = (type: number, src: string): WebGLShader => {
      const sh = gl.createShader(type);
      if (!sh) throw new Error("shader alloc failed");
      gl.shaderSource(sh, src);
      gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
        const which = type === gl.VERTEX_SHADER ? "vertex" : "fragment";
        // An empty log usually means the context is lost (e.g. a prior
        // loseContext) — surface both so the cause is never a mystery.
        const log = gl.getShaderInfoLog(sh) || "(empty log — context lost?)";
        console.error(`[GLRenderer] ${which} shader failed to compile:\n${log}`);
        throw new Error(`${which} shader compile failed: ${log}`);
      }
      return sh;
    };
    const prog = gl.createProgram();
    if (!prog) throw new Error("program alloc failed");
    gl.attachShader(prog, mk(gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, mk(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      throw new Error(gl.getProgramInfoLog(prog) ?? "program link failed");
    }
    gl.useProgram(prog);
    return prog;
  }

  /** Upload a normalized uint16 raster (row-major) as a packed texture. */
  setImage16(data: Uint16Array, w: number, h: number): void {
    const { gl } = this;
    const rgba = new Uint8Array(w * h * 4);
    for (let i = 0; i < w * h; i++) {
      const v = data[i];
      rgba[i * 4] = v >> 8; // R = hi byte
      rgba[i * 4 + 1] = v & 0xff; // G = lo byte
      rgba[i * 4 + 3] = 255;
    }
    if (this.tex) gl.deleteTexture(this.tex);
    this.tex = gl.createTexture();
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texImage2D(
      gl.TEXTURE_2D,
      0,
      gl.RGBA,
      w,
      h,
      0,
      gl.RGBA,
      gl.UNSIGNED_BYTE,
      rgba,
    );
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    this.imgSize = { w, h };

    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([0, 0, w, 0, 0, h, 0, h, w, 0, w, h]),
      gl.STATIC_DRAW,
    );
  }

  /** Upload a 256×1 RGBA colormap LUT. */
  setLut(rgba256: Uint8Array): void {
    const { gl } = this;
    if (!this.lut) this.lut = gl.createTexture();
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.lut);
    gl.texImage2D(
      gl.TEXTURE_2D,
      0,
      gl.RGBA,
      256,
      1,
      0,
      gl.RGBA,
      gl.UNSIGNED_BYTE,
      rgba256,
    );
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  }

  clear(): void {
    const { gl } = this;
    if (this.tex) {
      gl.deleteTexture(this.tex);
      this.tex = null;
    }
    this.imgSize = { w: 0, h: 0 };
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
  }

  draw(view: View, vp: Size, dpr: number, win: Window16): void {
    const { gl, canvas } = this;
    const pw = Math.max(1, Math.round(vp.w * dpr));
    const ph = Math.max(1, Math.round(vp.h * dpr));
    if (canvas.width !== pw || canvas.height !== ph) {
      canvas.width = pw;
      canvas.height = ph;
    }
    gl.viewport(0, 0, pw, ph);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    if (!this.tex || !this.lut || this.imgSize.w === 0) return;

    // pixel-exact above 1:1, smooth below (EM: never invent intensities)
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    const filter = view.z * dpr >= 1 ? gl.NEAREST : gl.LINEAR;
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, filter);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, filter);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.lut);

    gl.uniform2f(this.u("u_imgSize"), this.imgSize.w, this.imgSize.h);
    gl.uniform2f(this.u("u_vpSize"), vp.w, vp.h);
    gl.uniform3f(this.u("u_view"), view.z, view.px, view.py);
    gl.uniform4f(
      this.u("u_window"),
      win.lo,
      win.hi,
      win.gamma,
      win.invert ? 1.0 : 0.0,
    );
    gl.drawArrays(gl.TRIANGLES, 0, 6);
  }

  dispose(): void {
    const { gl } = this;
    if (this.tex) gl.deleteTexture(this.tex);
    if (this.lut) gl.deleteTexture(this.lut);
    gl.deleteProgram(this.prog);
    // NOTE: do NOT call WEBGL_lose_context.loseContext() here. getContext()
    // returns the SAME context object for a canvas, so force-losing it
    // poisons any renderer re-created on that canvas — which is exactly
    // what React StrictMode's mount→cleanup→mount does in dev, producing
    // a spurious "shader compile failed". Deleting the GL resources is
    // enough; the context is reclaimed when the canvas is GC'd.
  }
}
