"use strict";

module.exports = {
  ...require("./baseAdapter"),
  ...require("./filesystemAdapter"),
  ...require("./documentAdapter"),
  ...require("./httpAdapter"),
  ...require("./searchAdapter"),
  ...require("./processAdapter"),
};