// The game's Direct3D 8 calls run on Direct3D 9 through the vendored d3d8to9.
#include "d3d8to9.hpp"

extern "C" IDirect3D8 *d3d8to9_create(void)
{
    IDirect3D9 *d3d = Direct3DCreate9(D3D_SDK_VERSION);
    return d3d ? new Direct3D8(d3d) : nullptr;
}

extern "C" IDirect3DDevice9 *d3d9_device(IDirect3DDevice8 *dev)
{
    return static_cast<Direct3DDevice8 *>(dev)->GetProxyInterface();
}

extern "C" IDirect3DVertexBuffer9 *d3d9_vb(IDirect3DVertexBuffer8 *vb)
{
    return static_cast<Direct3DVertexBuffer8 *>(vb)->GetProxyInterface();
}

extern "C" IDirect3DIndexBuffer9 *d3d9_ib(IDirect3DIndexBuffer8 *ib)
{
    return static_cast<Direct3DIndexBuffer8 *>(ib)->GetProxyInterface();
}
