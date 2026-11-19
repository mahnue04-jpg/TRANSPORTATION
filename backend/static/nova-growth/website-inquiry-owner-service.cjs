'use strict';

// Staging-only service contract; caller must provide a server-verified principal.
// No Cloudflare token, production KV binding, route, or customer outreach here.
const { normalizeWebsiteLeadPage } = require('./website-lead-adapter.cjs');

class WebsiteInquiryAccessError extends Error {
  constructor(message, status) { super(message); this.name = 'WebsiteInquiryAccessError'; this.status = status; }
}
function isOwner(principal, organizationId) {
  return Boolean(principal && principal.authenticated === true &&
    principal.role === 'owner' &&
    typeof organizationId === 'string' && organizationId.length > 0 &&
    principal.organization_id === organizationId);
}
async function loadWebsiteInquiries({ principal, organizationId, source }) {
  if (!isOwner(principal, organizationId)) throw new WebsiteInquiryAccessError('Access denied', 403);
  if (!source || typeof source.list !== 'function') {
    return { status: 'unavailable', inquiries: null, reason: 'source_not_configured' };
  }
  try {
    const page = await source.list({ prefix: 'lead:' });
    if (!page || !Array.isArray(page.entries) || page.complete !== true) {
      return { status: 'unavailable', inquiries: null, reason: 'incomplete_source_page' };
    }
    const inquiries = normalizeWebsiteLeadPage(page.entries);
    return { status: 'ok', inquiries, source: 'staging_fixture', count: inquiries.length };
  } catch (_) {
    // Deliberately do not echo raw errors, credentials, or lead PII.
    return { status: 'unavailable', inquiries: null, reason: 'source_read_failed' };
  }
}
module.exports = { WebsiteInquiryAccessError, loadWebsiteInquiries };
