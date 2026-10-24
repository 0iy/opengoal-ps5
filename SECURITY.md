# Security

The app runs an unauthenticated web server (port 8080, ISO import) and a debug log channel on the local network. Use it only on a network you
trust. The installer talks to the console's FTP service (2121) and ELF loader (9021) in clear text.

Report vulnerabilities (for example in the web server, the importer's ISO parsing, or the installer) privately through the repository's
Security tab ("Report a vulnerability"). Do not post exploit details in public issues. Console or firmware exploits are out of scope.

Supported: the latest release only.
