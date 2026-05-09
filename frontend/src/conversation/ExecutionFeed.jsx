"use strict";

function buildExecutionFeedModel(entries) {
  var source = Array.isArray(entries) ? entries : [];
  var normalized = source.map(function (item) {
    return {
      at: item.at || Date.now(),
      type: item.type || "event",
      title: item.title || item.state || item.type || "event",
      details: item.details || item.payload || {},
    };
  });

  normalized.sort(function (a, b) { return a.at - b.at; });
  return normalized;
}

function ExecutionFeed(props) {
  return {
    type: "ExecutionFeed",
    entries: buildExecutionFeedModel(props && props.entries),
  };
}

module.exports = {
  ExecutionFeed: ExecutionFeed,
  buildExecutionFeedModel: buildExecutionFeedModel,
};
