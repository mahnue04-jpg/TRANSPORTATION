# Lifesaver V2 privacy model

Privacy ON: camera off, microphone off, tracking off, automatic video blocked, no stream, no hidden activation.

Privacy OFF does not turn camera, microphone, or tracking back on.

A future physical privacy switch (`PRIVACY_SWITCH_ON`) overrides software `PRIVACY_DISABLE`. GPIO is not connected.

Camera contract remains `stream_ready=false`. No video or audio is stored.
