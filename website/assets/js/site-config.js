/* Public, non-secret site settings only. Do not put SMTP, API, or Stripe keys here.
   siteOrigin: set after a *.pages.dev or *.github.io URL exists.
   formEndpoint: leave empty until LEAD_WEBHOOK_URL is configured. Then use "/api/leads". */
window.AMICOR_SITE = {
  siteOrigin: "",
  formEndpoint: ""
};
