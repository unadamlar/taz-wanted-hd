// PNG read/write through Windows Imaging Component (Wine provides it). Use from one thread only.
#define COBJMACROS
#include <windows.h>
#include <wincodec.h>
#include <stdlib.h>
#include "image.h"

static IWICImagingFactory *factory(void)
{
    static IWICImagingFactory *f;
    if (!f) // the calling thread must have initialised COM
        CoCreateInstance(&CLSID_WICImagingFactory, NULL, CLSCTX_INPROC_SERVER, &IID_IWICImagingFactory, (void **)&f);
    return f;
}

int png_write(const char *path, UINT w, UINT h, const BYTE *bgra)
{
    IWICImagingFactory *f = factory();
    IWICStream *stream = NULL;
    IWICBitmapEncoder *enc = NULL;
    IWICBitmapFrameEncode *frame = NULL;
    WCHAR wpath[MAX_PATH];
    WICPixelFormatGUID fmt = GUID_WICPixelFormat32bppBGRA;
    HRESULT hr = f ? S_OK : E_FAIL;

    MultiByteToWideChar(CP_ACP, 0, path, -1, wpath, MAX_PATH);
    if (SUCCEEDED(hr)) hr = IWICImagingFactory_CreateStream(f, &stream);
    if (SUCCEEDED(hr)) hr = IWICStream_InitializeFromFilename(stream, wpath, GENERIC_WRITE);
    if (SUCCEEDED(hr)) hr = IWICImagingFactory_CreateEncoder(f, &GUID_ContainerFormatPng, NULL, &enc);
    if (SUCCEEDED(hr)) hr = IWICBitmapEncoder_Initialize(enc, (IStream *)stream, WICBitmapEncoderNoCache);
    if (SUCCEEDED(hr)) hr = IWICBitmapEncoder_CreateNewFrame(enc, &frame, NULL);
    if (SUCCEEDED(hr)) hr = IWICBitmapFrameEncode_Initialize(frame, NULL);
    if (SUCCEEDED(hr)) hr = IWICBitmapFrameEncode_SetSize(frame, w, h);
    if (SUCCEEDED(hr)) hr = IWICBitmapFrameEncode_SetPixelFormat(frame, &fmt);
    if (SUCCEEDED(hr)) hr = IWICBitmapFrameEncode_WritePixels(frame, h, w * 4, w * h * 4, (BYTE *)bgra);
    if (SUCCEEDED(hr)) hr = IWICBitmapFrameEncode_Commit(frame);
    if (SUCCEEDED(hr)) hr = IWICBitmapEncoder_Commit(enc);

    if (frame) IWICBitmapFrameEncode_Release(frame);
    if (enc) IWICBitmapEncoder_Release(enc);
    if (stream) IWICStream_Release(stream);
    return SUCCEEDED(hr);
}

BYTE *png_read(const char *path, UINT *w, UINT *h)
{
    IWICImagingFactory *f = factory();
    IWICBitmapDecoder *dec = NULL;
    IWICBitmapFrameDecode *frame = NULL;
    IWICFormatConverter *conv = NULL;
    WCHAR wpath[MAX_PATH];
    BYTE *pixels = NULL;
    HRESULT hr = f ? S_OK : E_FAIL;

    MultiByteToWideChar(CP_ACP, 0, path, -1, wpath, MAX_PATH);
    if (SUCCEEDED(hr)) hr = IWICImagingFactory_CreateDecoderFromFilename(f, wpath, NULL, GENERIC_READ, WICDecodeMetadataCacheOnDemand, &dec);
    if (SUCCEEDED(hr)) hr = IWICBitmapDecoder_GetFrame(dec, 0, &frame);
    if (SUCCEEDED(hr)) hr = IWICImagingFactory_CreateFormatConverter(f, &conv);
    if (SUCCEEDED(hr)) hr = IWICFormatConverter_Initialize(conv, (IWICBitmapSource *)frame, &GUID_WICPixelFormat32bppBGRA,
                                                            WICBitmapDitherTypeNone, NULL, 0.0, WICBitmapPaletteTypeCustom);
    if (SUCCEEDED(hr)) hr = IWICFormatConverter_GetSize(conv, w, h);
    if (SUCCEEDED(hr) && (pixels = malloc((size_t)*w * *h * 4)) == NULL) hr = E_OUTOFMEMORY;
    if (SUCCEEDED(hr)) hr = IWICFormatConverter_CopyPixels(conv, NULL, *w * 4, *w * *h * 4, pixels);

    if (conv) IWICFormatConverter_Release(conv);
    if (frame) IWICBitmapFrameDecode_Release(frame);
    if (dec) IWICBitmapDecoder_Release(dec);
    if (FAILED(hr)) {
        free(pixels);
        return NULL;
    }
    return pixels;
}
