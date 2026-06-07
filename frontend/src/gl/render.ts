// Minimal WebGL image renderer (handoff §13 render path). Phase 1 draws
// the backend's 8-bit /render PNG as a texture; Phase 2 swaps the texture
// for raw data + a window/level/γ/LUT fragment shader — same draw call.

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
precision mediump float;
uniform sampler2D u_tex;
varying vec2 v_uv;
void main() {
  gl_FragColor = texture2D(u_tex, v_uv);
}`;

export class GLRenderer {
  private gl: WebGLRenderingContext;
  private prog: WebGLProgram;
  private tex: WebGLTexture | null = null;
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
  }

  private compile(): WebGLProgram {
    const { gl } = this;
    const mk = (type: number, src: string): WebGLShader => {
      const sh = gl.createShader(type);
      if (!sh) throw new Error("shader alloc failed");
      gl.shaderSource(sh, src);
      gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
        throw new Error(gl.getShaderInfoLog(sh) ?? "shader compile failed");
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

  /** Upload a decoded PNG as the stage texture. */
  setImage(img: HTMLImageElement): void {
    const { gl } = this;
    if (this.tex) gl.deleteTexture(this.tex);
    this.tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
    // NEAREST when zoomed in (see draw); pixel-exact inspection matters in EM
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    this.imgSize = { w: img.naturalWidth, h: img.naturalHeight };

    const { w, h } = this.imgSize;
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([0, 0, w, 0, 0, h, 0, h, w, 0, w, h]),
      gl.STATIC_DRAW,
    );
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

  draw(view: View, vp: Size, dpr: number): void {
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
    if (!this.tex || this.imgSize.w === 0) return;

    // pixel-exact above 1:1, smooth below
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    const filter = view.z * dpr >= 1 ? gl.NEAREST : gl.LINEAR;
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, filter);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, filter);

    const u = (name: string) => gl.getUniformLocation(this.prog, name);
    gl.uniform2f(u("u_imgSize"), this.imgSize.w, this.imgSize.h);
    gl.uniform2f(u("u_vpSize"), vp.w, vp.h);
    gl.uniform3f(u("u_view"), view.z, view.px, view.py);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
  }

  dispose(): void {
    if (this.tex) this.gl.deleteTexture(this.tex);
    this.gl.getExtension("WEBGL_lose_context")?.loseContext();
  }
}
