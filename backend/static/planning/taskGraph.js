"use strict";

const { createTask } = require("./planningSchemas");

function createTaskGraph(tasksInput) {
  var tasks = Array.isArray(tasksInput) ? tasksInput.map(createTask) : [];
  var nodes = Object.create(null);
  var adjacency = Object.create(null);
  var reverse = Object.create(null);

  for (var i = 0; i < tasks.length; i++) {
    var task = tasks[i];
    if (nodes[task.id]) {
      throw new Error("Duplicate task id: " + task.id);
    }
    nodes[task.id] = task;
    adjacency[task.id] = [];
    reverse[task.id] = [];
  }

  var ids = Object.keys(nodes).sort();
  for (var j = 0; j < ids.length; j++) {
    var id = ids[j];
    var deps = nodes[id].dependencies;
    for (var k = 0; k < deps.length; k++) {
      var depId = deps[k];
      if (!nodes[depId]) {
        throw new Error("Unknown dependency '" + depId + "' in task '" + id + "'");
      }
      adjacency[depId].push(id);
      reverse[id].push(depId);
    }
  }

  for (var a = 0; a < ids.length; a++) {
    adjacency[ids[a]].sort();
    reverse[ids[a]].sort();
  }

  return {
    tasks: tasks,
    nodes: nodes,
    ids: ids,
    adjacency: adjacency,
    reverse: reverse,
    getTask: function (id) {
      return nodes[id] || null;
    },
    getDependents: function (id) {
      return (adjacency[id] || []).slice();
    },
    getDependencies: function (id) {
      return (reverse[id] || []).slice();
    },
  };
}

function detectCycles(graph) {
  var visited = Object.create(null);
  var stack = Object.create(null);
  var cycles = [];

  function dfs(nodeId, path) {
    visited[nodeId] = true;
    stack[nodeId] = true;
    path.push(nodeId);

    var next = graph.getDependents(nodeId);
    for (var i = 0; i < next.length; i++) {
      var dep = next[i];
      if (!visited[dep]) {
        dfs(dep, path);
      } else if (stack[dep]) {
        var idx = path.indexOf(dep);
        var cycle = path.slice(idx).concat(dep);
        cycles.push(cycle);
      }
    }

    stack[nodeId] = false;
    path.pop();
  }

  var ids = graph.ids.slice().sort();
  for (var i = 0; i < ids.length; i++) {
    if (!visited[ids[i]]) {
      dfs(ids[i], []);
    }
  }

  return {
    hasCycle: cycles.length > 0,
    cycles: cycles,
  };
}

function topologicalSort(graph) {
  var indegree = Object.create(null);
  var queue = [];
  var ordered = [];

  for (var i = 0; i < graph.ids.length; i++) {
    var id = graph.ids[i];
    indegree[id] = graph.getDependencies(id).length;
    if (indegree[id] === 0) {
      queue.push(id);
    }
  }
  queue.sort();

  while (queue.length > 0) {
    var current = queue.shift();
    ordered.push(current);
    var dependents = graph.getDependents(current);
    for (var j = 0; j < dependents.length; j++) {
      indegree[dependents[j]] -= 1;
      if (indegree[dependents[j]] === 0) {
        queue.push(dependents[j]);
      }
    }
    queue.sort();
  }

  if (ordered.length !== graph.ids.length) {
    throw new Error("Unable to topologically sort graph with cycles");
  }

  return ordered;
}

function computeDepth(graph) {
  var memo = Object.create(null);

  function depthOf(taskId) {
    if (memo[taskId] !== undefined) {
      return memo[taskId];
    }
    var deps = graph.getDependencies(taskId);
    if (deps.length === 0) {
      memo[taskId] = 1;
      return 1;
    }

    var best = 0;
    for (var i = 0; i < deps.length; i++) {
      best = Math.max(best, depthOf(deps[i]));
    }

    memo[taskId] = best + 1;
    return memo[taskId];
  }

  var ids = graph.ids;
  var maxDepth = 0;
  for (var i = 0; i < ids.length; i++) {
    maxDepth = Math.max(maxDepth, depthOf(ids[i]));
  }
  return maxDepth;
}

module.exports = {
  createTaskGraph: createTaskGraph,
  detectCycles: detectCycles,
  topologicalSort: topologicalSort,
  computeDepth: computeDepth,
};
