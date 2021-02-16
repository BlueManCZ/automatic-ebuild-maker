# Automatic ebuild maker

I created this script to help me with converting .deb packages to .ebuild files.
It is focused especially on packages based on Electron framework. The script tries to extract
as much as possible information from .deb archive and fill extracted data to the
[.ebuild template](https://github.com/BlueManCZ/automatic-ebuild-maker/blob/master/templates/template.ebuild).

## Features

- Automatic detection of `DESCRIPTION`, `HOMEPAGE` and `LICENSE` 
- The smart build of `SRC_URI` for multiple architectures
- Conversion from .deb dependencies to Portage `RDEPEND` dependencies
- Dynamic `IUSE` and `KEYWORDS` filling
- Automatic metadata.xml file creation with use flags descriptions
- `--system-ffmpeg` and `--system-mesa` flags for removing shipped build-in libraries

## Dependencies

```shell
pip3 install -r requirements.txt --user
```

## Usage

If the package is provided only for one CPU architecture, simply use full download URL:

```shell
./automatic-ebuild-maker.py --url https://github.com/swiftyapp/swifty/releases/download/v0.6.4/Swifty_0.6.4_amd64.deb --system-mesa --system-ffmpeg --verbose
```

[Result](https://github.com/BlueManCZ/edgets/tree/master/app-crypt/swifty)

<hr>

If package is available in multiple architectures, specify them with custom flags (e.g. `--amd64`, `--i386`, etc.) and use `@ARCH@` variable in url address:

```shell
./automatic-ebuild-maker.py --url https://github.com/martpie/museeks/releases/download/0.11.5/museeks-@ARCH@.deb --amd64 --i386 --system-ffmpeg --system-mesa --verbose
```

[Result](https://github.com/BlueManCZ/edgets/tree/master/media-sound/museeks)

<hr>

You can specify custom `LICENSE` and `HOMEPAGE` with `--license` and `--homepage` flags.

```shell
./automatic-ebuild-maker.py --help
```
