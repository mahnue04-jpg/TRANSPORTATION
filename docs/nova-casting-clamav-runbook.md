# Disposable ClamAV runbook for Nova Casting

This runbook is for a disposable test machine. It does not install ClamAV on Render or any other real host, and it does not enable public media uploads.

Structural checks are not maintained antivirus. `antivirus_ready` is true only when `NOVA_CASTING_SCANNER=clamav`, `clamscan` is on `PATH`, and the configured signature files are present and newer than seven days.

## What was verified on 2026-10-11

On this disposable agent machine, Ubuntu package `clamav` `1.5.4+dfsg-0ubuntu0.24.04.1` installed from `archive.ubuntu.com`. `freshclam` wrote signatures into `/tmp/clamav-db`:

- `daily.cvd` version 28150
- `main.cvd` version 63
- `bytecode.cvd` version 339

`scanner_capability()` reported `mode=antivirus`, `antivirus_ready=true`, reason `Antivirus signatures are current.` A synthetic MP4 was accepted with engine `clamscan`. A direct `clamscan --database /tmp/clamav-db` of the EICAR test string exited 1 with `Eicar-Signature FOUND`. An EICAR marker appended to an MP4 is still rejected by the structural check before ClamAV runs, with engine `structural`.

`freshclam` printed `NotifyClamd: Can't find or parse configuration file /etc/clamav/clamd.conf`. That message is expected. This runbook does not start `clamd`. `clamscan` is the scanner.

## Disposable setup

```bash
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y clamav clamav-freshclam
mkdir -p /tmp/clamav-db
sudo freshclam --stdout --datadir=/tmp/clamav-db
export NOVA_CASTING_SCANNER=clamav
export NOVA_CASTING_CLAMAV_DB=/tmp/clamav-db
```

The casting sandbox flag and a non-production environment are still required before any upload route opens. Leave `NOVA_CASTING_SCANNER` unset to stay in structural-only mode.

## Fail closed

- Scanner binary missing: upload is rejected and `antivirus_ready` is false.
- Signature directory missing, empty, or older than seven days: upload is rejected and ClamAV is not asked to bless the file.
- `clamscan` timeout, crash, or non-zero exit: upload is rejected.
- Unknown `NOVA_CASTING_SCANNER` value: upload is rejected.
- Production environment names keep the sandbox routes closed even if ClamAV is installed.

Unit coverage for those cases is in `backend/tests/test_nova_casting_media_scan.py`. Those tests do not download signatures and do not require the `clamav` package.
