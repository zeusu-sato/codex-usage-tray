# Native runtime notices

These files cover the reviewed CPython **3.13.15 Windows x64** package. They are copied from the pinned OpenSSL release and CPython's pinned source dependencies; `native-runtime.json` records their source URLs and SHA-256 hashes. The nested `.gitattributes` preserves their original bytes.

CPython's [version declaration](https://github.com/python/cpython/blob/4061bc4c35f7c26f25264666d4ba083b93d2f6f9/PCbuild/get_externals.bat) selects OpenSSL 3.0.21. The official [embeddable distribution](https://www.python.org/ftp/python/3.13.15/python-3.13.15-embed-amd64.zip) supplies the binary and Python-license hashes. Its reviewed native files match the application's previous CPython 3.13.15 CI package byte for byte; `libcrypto-3.dll` also matches CPython's pinned binary dependency.

OpenSSL's pinned source tree has `LICENSE.txt` and no top-level `NOTICE`. `OPENSSL-NOTICE.txt` is explicitly our distributor attribution. XZ's notice describes the public-domain liblzma used by Python; the XZ command-line tools and build system are not bundled here.

The collector runs offline. It rejects an unsupported interpreter, changed Python license, unknown native component, or mismatched reviewed binary/notice hash before copying notices. Windows API/CRT support DLLs supplied by the build environment are inventoried separately. A new runtime requires reviewing its dependency versions, notices, and binary provenance and updating this manifest; do not bypass validation or reuse these notices blindly.
