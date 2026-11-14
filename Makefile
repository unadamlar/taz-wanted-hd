CC = i686-w64-mingw32-gcc
CFLAGS = -O2 -Wall -Wextra -Wno-unused-parameter
SRC = $(wildcard src/d3d8/*.c)

build/d3d8.dll: $(SRC) $(wildcard src/d3d8/*.h)
	@mkdir -p build
	$(CC) $(CFLAGS) -shared -o $@ $(SRC) -Wl,--kill-at -static-libgcc -lole32 -luuid -lwindowscodecs -ldxguid -lgdi32 -luser32

# Player installer, without the mod's files; tools/pack-installer.py appends them.
installer: build/installer.exe

build/installer.exe: src/installer/install.c src/installer/install.rc src/installer/install.manifest
	@mkdir -p build
	i686-w64-mingw32-windres -I src/installer src/installer/install.rc -O coff -o build/installer-res.o
	$(CC) $(CFLAGS) -Wno-missing-field-initializers -Os -s -municode -mwindows -static -o $@ src/installer/install.c build/installer-res.o -lcomctl32 -lshell32 -lole32 -luuid

.PHONY: installer
