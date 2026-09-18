# Lifesaver V2 privacy model

Connected-health and home-test records use separate consents. Revocation stops future sharing. Audit metadata must not include reading values, result contents, journal text, or device secrets.

Privacy ON: camera off, microphone off, tracking off, automatic video blocked, no stream, no hidden activation.

Privacy OFF does not turn camera, microphone, or tracking back on.

A future physical privacy switch (`PRIVACY_SWITCH_ON`) overrides software `PRIVACY_DISABLE`. GPIO is not connected.

Camera contract remains `stream_ready=false`. No video or audio is stored.
