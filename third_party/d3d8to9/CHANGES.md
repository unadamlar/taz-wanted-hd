# Changes from upstream

Source: https://github.com/crosire/d3d8to9 at commit 255338f698c8270b537f0a91a13f795f4f988250 (BSD-2, see LICENSE.md).
Only the files that are built are kept. Compiled into the mod's `d3d8.dll` (see the Makefile), with `D3D8TO9NOLOG`.

- Removed `d3d8to9.cpp` and `d3dx9.hpp`: the mod has its own `Direct3DCreate8` (`src/d3d8/proxy.c`, `src/d3d8/d3d9.cpp`).
  No D3DX: stock Windows doesn't ship `d3dx9_43.dll` and Wine implements it only partly.
- `CreateVertexShader`: no disassemble/reassemble. `TranslateVertexShader` keeps the vs_1_x bytecode, adds `dcl` tokens from
  the declaration and `def` tokens for its constants, and makes oFog/oPts writes whole-register with `.x` sources.
- `CreatePixelShader`: ps_1_x bytecode is passed through unchanged.
- `CopyRects`: `CopyByLock` replaces `D3DXLoadSurfaceFromSurface` (same format, no scaling; render targets read back through
  system memory).
- State blocks now save and restore what the wrapper tracks itself (current vertex/pixel shader handle, base vertex index).
  Upstream left `GetVertexShader` returning the shader of the last `SetVertexShader` after an Apply. `Reset` clears them.
- `SetVertexShader` refuses a deleted handle, as Direct3D 8 does; upstream followed the freed pointer.
