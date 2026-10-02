# Third-party notices

This application uses the following third-party components. The original HAF
Iris controller source is licensed separately under MPL-2.0; see `LICENSE`.
The components below retain their own licenses and notices.

## LibreHardwareMonitor and related sensor libraries

The compiled helper includes these Mozilla Public License 2.0 components:

| Component | Version | Project |
| --- | ---: | --- |
| LibreHardwareMonitorLib | 0.9.6 | https://github.com/LibreHardwareMonitor/LibreHardwareMonitor |
| DiskInfoToolkit | 1.1.2 | https://github.com/Blacktempel/DiskInfoToolkit |
| RAMSPDToolkit-NDD | 1.4.2 | https://github.com/Blacktempel/RAMSPDToolkit |
| BlackSharp.Core | 1.0.7 | https://github.com/Blacktempel/BlackSharp |

Their MPL-2.0 license text is the same text included as the top-level `LICENSE`.
LibreHardwareMonitorLib was consumed through its published NuGet package; this
project does not copy or modify its source files.

## HidSharp

HidSharp 2.6.4 by James F. Bellinger is included as a transitive dependency.
Its package-provided license is reproduced in `licenses/HidSharp-LICENSE.txt`.

Project: https://software.seekye.com/hidsharp

## Microsoft .NET libraries

The helper distribution includes Microsoft `System.IO.Ports` 10.0.3,
`System.Management` 10.0.2, and `System.Threading.AccessControl` 10.0.3.
Their package metadata declares the MIT license. The MIT license is included as
`licenses/dotnet-MIT.txt`, and the package-provided consolidated notices are in
`licenses/dotnet-THIRD-PARTY-NOTICES.txt`.

Project: https://github.com/dotnet/dotnet

## Python packages

The application expects Pillow and pystray, as listed in `requirements.txt`.
They are installed separately and are not vendored in this directory. Consult
their distributions for the license text corresponding to the installed
versions.
