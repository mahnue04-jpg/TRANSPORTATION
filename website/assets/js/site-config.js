/* Public, non-secret site settings only. Do not put SMTP, API, or Stripe keys here.
   firstCustomerFunnel stays off. This package does not publish /start/ or the
   research-memo guide, and it must not set firstCustomerFunnel to true. */
window.AMICOR_SITE = {
  siteOrigin: "https://getamicor.com",
  formEndpoint: "/api/leads",
  publicContactEmail: "info@getamicor.com"
};
