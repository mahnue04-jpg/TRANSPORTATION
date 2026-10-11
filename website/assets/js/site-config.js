/* Public, non-secret site settings only. Do not put SMTP, API, or Stripe keys here.
   firstCustomerFunnel is read by scripts/build-production.mjs. false removes
   /start/ and /guides/research-memo-setup/ from the production build. The
   Pages functions deny those direct URLs while the published flag is false.
   Local preview serves this source tree. noindex is not the gate. */
window.AMICOR_SITE = {
  siteOrigin: "https://getamicor.com",
  formEndpoint: "/api/leads",
  publicContactEmail: "info@getamicor.com",
  firstCustomerFunnel: false,
  affiliateEnrollment: "pending"
};
