"use strict";

module.exports = {
  ...require("./capabilitySchemas"),
  ...require("./workflowTemplates"),
  ...require("./documentWorkflow"),
  ...require("./taskManager"),
  ...require("./schedulingAssistant"),
  ...require("./emailAssistant"),
  ...require("./reportGenerator"),
  ...require("./businessSummarizer"),
  ...require("./researchAssistant"),
  ...require("./capabilityRouter"),
};
