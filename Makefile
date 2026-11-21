CC = i686-w64-mingw32-gcc
CXX = i686-w64-mingw32-g++
CFLAGS = -O2 -Wall -Wextra -Wno-unused-parameter
D3D8TO9 = third_party/d3d8to9/source
CXXFLAGS = -O2 -std=c++17 -w -DD3D8TO9NOLOG -I$(D3D8TO9)
SRC = $(wildcard src/d3d8/*.c)
CXXSRC = $(wildcard src/d3d8/*.cpp) $(wildcard $(D3D8TO9)/*.cpp)
OBJ = $(patsubst %.c,build/obj/%.o,$(SRC)) $(patsubst %.cpp,build/obj/%.o,$(CXXSRC))

build/d3d8.dll: $(OBJ)
	$(CXX) $(OBJ) -shared -o $@ -Wl,--kill-at -static -lole32 -luuid -lwindowscodecs -ldxguid -lgdi32 -luser32 -ld3d9

build/obj/%.o: %.c $(wildcard src/d3d8/*.h)
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

build/obj/%.o: %.cpp $(wildcard $(D3D8TO9)/*.hpp)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) -c $< -o $@

# Player installer, without the mod's files; tools/pack-installer.py appends them.
installer: build/installer.exe

build/installer.exe: src/installer/install.c src/installer/install.rc src/installer/install.manifest
	@mkdir -p build
	i686-w64-mingw32-windres -I src/installer src/installer/install.rc -O coff -o build/installer-res.o
	$(CC) $(CFLAGS) -Wno-missing-field-initializers -Os -s -municode -mwindows -static -o $@ src/installer/install.c build/installer-res.o -lcomctl32 -lshell32 -lole32 -luuid

.PHONY: installer
