CC = i686-w64-mingw32-gcc
CFLAGS = -O2 -Wall -Wextra -Wno-unused-parameter
SRC = $(wildcard src/d3d8/*.c)

build/d3d8.dll: $(SRC) $(wildcard src/d3d8/*.h)
	@mkdir -p build
	$(CC) $(CFLAGS) -shared -o $@ $(SRC) -Wl,--kill-at -static-libgcc -lole32 -luuid -lwindowscodecs
