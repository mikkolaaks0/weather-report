# Windows release signing

Smart App Control can block a newly built `WeatherReport.exe` or one of its
native dependencies when it cannot establish trust. A checksum verifies a
download's contents; it does not establish a Windows publisher identity.
The distribution needs Authenticode signatures from a publicly trusted code
signing provider. A self-signed certificate, even one manually trusted on the
build machine, does not provide public trust. Microsoft describes the current
requirements in [Sign your app for Smart App Control compliance](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control).

The build and both release entrypoints enforce Windows signature verification.
This repository does not include a signing identity or private key. Signing
must be configured before producing a distributable release. These changes
cannot repair previously downloaded unsigned executables; those need to be
replaced by a newly built, correctly signed package. Smart App Control and
Defender settings do not need to be changed.

## Configure one signing method

### A certificate in the Windows certificate store

Install the provider's signing tools and make Windows SDK `signtool.exe`
available on `PATH`. Use a current code signing certificate with access to its
private key in `Cert:\CurrentUser\My`. Hardware-backed certificates can use
their provider's installed key storage driver. The key stays in its provider's
protected storage; the build receives only its public certificate thumbprint.

```powershell
$env:WEATHERREPORT_SIGNING_CERTIFICATE = 'YOUR_40_HEX_CHARACTER_CERTIFICATE_THUMBPRINT'
powershell -NoProfile -File .\build_release.ps1 -SkipInstaller
```

The signer uses SHA-256 for the file digest and RFC 3161 timestamp digest.
`WEATHERREPORT_TIMESTAMP_URL` optionally overrides the default timestamp service
`https://timestamp.digicert.com`; use the service recommended by your provider.
Failure to sign or timestamp stops the build.

### A signing service or provider hook

Set `WEATHERREPORT_SIGNING_SCRIPT` to a trusted PowerShell script. It is an
alternative to `WEATHERREPORT_SIGNING_CERTIFICATE`; do not configure both.

```powershell
$env:WEATHERREPORT_SIGNING_SCRIPT = 'C:\BuildTools\Sign-WeatherReport.ps1'
powershell -NoProfile -File .\build_release.ps1 -SkipInstaller
```

The hook is called once per unsigned native file with `-Path` containing its
literal absolute filename. It must sign that file in place using a publicly
trusted identity, add a trusted timestamp, and throw or exit nonzero on failure.
The build independently checks the result with `Get-AuthenticodeSignature`.
Keep service credentials in the provider's protected credential store or CI
secrets. Do not put tokens, PFX files, passwords, or private keys in the repo.

For GitHub's hosted `Release` workflow, configure repository variable
`WEATHERREPORT_SIGNING_SCRIPT` to a repository-owned hook's path, and configure
the provider credentials it needs. The workflow exposes the optional GitHub
secret `WEATHERREPORT_SIGNING_TOKEN` only in the release job. The provider hook
must also arrange its own SDK/client prerequisites. No signing provider or
paid service is provisioned automatically. Until this is configured, a version
tag's release build stops with a signing-configuration error and publishes no
unsigned package. Normal branch/PR tests do not require signing credentials.

## What is signed and checked

- Every `.exe`, `.dll`, and `.pyd` in `dist/WeatherReport` is inspected.
  Existing valid Python/Microsoft/vendor signatures are preserved. Unsigned
  binaries, including WeatherReport and unsigned Pillow modules, are signed.
  Invalid existing signatures stop the build rather than being overwritten.
- UPX compression is disabled so it cannot invalidate vendor signatures.
- Inno Setup receives the same signer during compilation, with
  `SignedUninstaller=yes`. This signs the installer, its temporary executable
  copies, and the uninstaller. Signing only the final Setup EXE is insufficient.
  See [Inno Setup's SignTool documentation](https://jrsoftware.org/ishelp/topic_setup_signtool.htm).
- ZIP creation and SHA-256 checksums follow payload signing. The resulting ZIP
  is extracted and all native signatures are checked again. Both local and CI
  publishing repeat this check before creating a tag or contacting the Release
  API. A local unsigned test package cannot pass this publication check.

Windows reports local Authenticode trust; it does not prove that a certificate
is publicly trusted on every destination computer. Use a public production
identity, and test the final package with Smart App Control on a clean test
machine before distribution. Reputation checks and other security policies can
also affect execution. No system security policy is changed by the build.

## Local tests without signing credentials

Run the source normally, or explicitly request an unsigned local test package:

```powershell
powershell -NoProfile -File .\build_release.ps1 -SkipInstaller -AllowUnsigned
```

This option permits a missing signing configuration only. A configured signer
that fails never falls back to an unsigned package. `publish_release.ps1` has
no unsigned option. Unsigned builds may still be blocked by Windows and must
not be distributed as a Smart App Control fix.
