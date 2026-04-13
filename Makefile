GO       = go
DLL      = paz_core.dll
SRC      = paz_core
DIST     = dist\plugins
PKG      = basic_games\games\crimsondesert
PLUGINS  = plugins

export CGO_ENABLED = 1
export GOOS        = windows
export GOARCH      = amd64

ifneq ($(OS),Windows_NT)
export CC = x86_64-w64-mingw32-gcc
SEP      = /
DIST     = dist/plugins
PKG      = basic_games/games/crimsondesert
PLUGINS  = plugins
MKDIR    = mkdir -p
CP       = cp
RM       = rm -f
RMDIR    = rm -rf
else
SEP      = $(strip \)
MKDIR    = mkdir
CP       = copy /Y
RM       = del /Q
RMDIR    = rmdir /S /Q
endif

.PHONY: all dll dist clean

all: dist

dll:
	cd $(SRC) && $(GO) build -buildmode=c-shared -o ..$(SEP)$(DLL) .

ifneq ($(OS),Windows_NT)
dist: dll
	mkdir -p $(DIST)/$(PKG)
	cp $(DLL) $(DIST)/$(PKG)/
	cp $(PLUGINS)/$(PKG)/core.py         $(DIST)/$(PKG)/
	cp $(PLUGINS)/$(PKG)/builder.py      $(DIST)/$(PKG)/
	cp $(PLUGINS)/$(PKG)/constants.py    $(DIST)/$(PKG)/
	cp $(PLUGINS)/$(PKG)/mod_classify.py $(DIST)/$(PKG)/
	cp $(PLUGINS)/$(PKG)/util.py         $(DIST)/$(PKG)/
	cp $(PLUGINS)/$(PKG)/__init__.py     $(DIST)/$(PKG)/
	cp $(PLUGINS)/basic_games/games/game_crimsondesert.py $(DIST)/basic_games/games/
	cp $(PLUGINS)/installer_crimsondesert.py $(DIST)/
	cp $(PLUGINS)/tool_crimsondesert.py $(DIST)/
	rm -f $(DLL) paz_core.h $(SRC)/paz_core.h
	@echo "dist ready: $(DIST)/"

clean:
	rm -rf dist
	rm -f $(DLL) paz_core.h $(SRC)/paz_core.h $(SRC)/paz_core.dll $(SRC)/paz_core.so
else
dist: dll
	-@mkdir dist\plugins\basic_games\games\crimsondesert 2>nul
	@copy /Y $(DLL) $(DIST)\$(PKG)\ >nul
	@copy /Y $(PLUGINS)\$(PKG)\core.py         $(DIST)\$(PKG)\ >nul
	@copy /Y $(PLUGINS)\$(PKG)\builder.py      $(DIST)\$(PKG)\ >nul
	@copy /Y $(PLUGINS)\$(PKG)\constants.py    $(DIST)\$(PKG)\ >nul
	@copy /Y $(PLUGINS)\$(PKG)\mod_classify.py $(DIST)\$(PKG)\ >nul
	@copy /Y $(PLUGINS)\$(PKG)\util.py         $(DIST)\$(PKG)\ >nul
	@copy /Y $(PLUGINS)\$(PKG)\__init__.py     $(DIST)\$(PKG)\ >nul
	@copy /Y $(PLUGINS)\basic_games\games\game_crimsondesert.py $(DIST)\basic_games\games\ >nul
	@copy /Y $(PLUGINS)\installer_crimsondesert.py $(DIST)\ >nul
	@copy /Y $(PLUGINS)\tool_crimsondesert.py $(DIST)\ >nul
	-@del /Q $(DLL) paz_core.h 2>nul
	-@del /Q $(SRC)\paz_core.h 2>nul
	@echo dist ready: $(DIST)\

clean:
	-@rmdir /S /Q dist 2>nul
	-@del /Q $(DLL) paz_core.h $(SRC)\paz_core.h $(SRC)\paz_core.dll 2>nul
endif
