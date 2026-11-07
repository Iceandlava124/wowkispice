# ngspice license -- snippet for this project's redistribution audit

Read from file on disk: `tools/ngspice/docs/COPYING` (45,714 bytes).

First lines of that file, verbatim:

```
Ngspice Licensing

Copyright (c) 2026 by ngspice team
All rights reserved.

license for this document: CC-BY-SA v4.0
```

The part relevant to this project's redistribution story is the paragraph right
below that, in the same file:

```
The ngspice source code has evolved over time by integrating contributions
from various sources (e.g.  Spice3f5, XSPICE, CIDER, numparam, tclspice and
others).  Thus a mixture of license statements prevails.

The ngspice license is the `Modified BSD' license. This is adopted for all of
its source code, test and example files except for the files listed below.

************** files with licenses different to 'Modified BSD' ****************

* ngspice/m4
unnamed, compatible to DFSG

* ngspice/src/tclspice.c
LGPLv2

* all files in ngspice/src/maths/sparse
unnamed MIT license, compatible to New BSD

* all files in ngspice/src/maths/KLU
LGPLv2

* all files in ngspice/src/osdi
MPLv2.0

ngspice/src/spicelib/devices/ndev
public domain

ngspice/src/xspice
public domain
except for
ngspice/src/xspice/icm/table
GPLv2 or newer

ngspice/src/frontend/numparam
LGPLv2 or newer

ngspice manual
(see https://sourceforge.net/p/ngspice/ngspice-manuals/ci/master/tree/)
Creative Commons Attribution Share-Alike (CC-BY-SA) v4.0
```

So the bound obligation story for this project is:

- The file the project downloads and uses is the ngspice shared library
  (`tools/ngspice_dll/.../ngspice.dll`), which is a binary build.
- The license text this project has on disk for ngspice is the `tools/ngspice/docs/COPYING`
  file, which states the ngspice license is the `Modified BSD` license, with some
  subcomponents under `LGPLv2`, `LGPLv2 or newer`, `GPLv2 or newer`, `MPLv2.0`,
  unnamed MIT-style, public domain, and the manual under CC-BY-SA v4.0.
- This project does not quote that file into the public docs. It points at
  `THIRD_PARTY_NOTICES.md` and the binary/copyright banner instead.

This file exists so the public-facing docs can be audited against the actual file
on disk instead of invented legal summaries.
