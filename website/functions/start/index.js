import { gateFunnelRequest } from "../_funnel-gate.js";

export function onRequest(context) {
  return gateFunnelRequest(context);
}
