"use strict";

const { ROLES, ROLE_RANK, createAuthError, createAuthSuccess, AUTH_ERRORS, clone } = require("./authSchemas");

var BUILT_IN_ROLE_PERMISSIONS = {
  guest: ["read:public"],
  user: ["read:public", "read:own", "write:own", "run:workflow", "use:assistant"],
  admin: ["read:public", "read:own", "write:own", "read:all", "write:all", "run:workflow", "use:assistant", "manage:users"],
  owner: ["*"],
};

function hasWildcard(permissions) {
  return permissions.indexOf("*") !== -1;
}

function createPermissionManager(options) {
  var config = Object.assign({ enforceRoleHierarchy: true }, options || {});

  // userId -> Set of extra permissions
  var userPermissions = new Map();
  // userId -> role override (null = use default from user record)
  var userRoles = new Map();

  function getEffectivePermissions(userId, role) {
    var r = userRoles.get(String(userId)) || String(role || ROLES.user);
    var rolePerms = BUILT_IN_ROLE_PERMISSIONS[r] || BUILT_IN_ROLE_PERMISSIONS.guest;
    var extra = userPermissions.get(String(userId));
    if (!extra) return rolePerms.slice();
    var combined = rolePerms.slice();
    extra.forEach(function (p) {
      if (combined.indexOf(p) === -1) combined.push(p);
    });
    return combined;
  }

  function check(userId, role, permission) {
    var perms = getEffectivePermissions(userId, role);
    if (hasWildcard(perms)) return true;
    return perms.indexOf(String(permission)) !== -1;
  }

  function checkRole(userRole, requiredRole) {
    var userRank = ROLE_RANK[String(userRole || ROLES.guest)] || 0;
    var reqRank = ROLE_RANK[String(requiredRole || ROLES.guest)] || 0;
    return userRank >= reqRank;
  }

  function checkAll(userId, role, permissions) {
    var perms = getEffectivePermissions(userId, role);
    if (hasWildcard(perms)) return true;
    for (var i = 0; i < permissions.length; i++) {
      if (perms.indexOf(String(permissions[i])) === -1) return false;
    }
    return true;
  }

  function checkAny(userId, role, permissions) {
    var perms = getEffectivePermissions(userId, role);
    if (hasWildcard(perms)) return true;
    for (var i = 0; i < permissions.length; i++) {
      if (perms.indexOf(String(permissions[i])) !== -1) return true;
    }
    return false;
  }

  function grantPermission(userId, permission) {
    var uid = String(userId || "");
    if (!userPermissions.has(uid)) userPermissions.set(uid, new Set());
    userPermissions.get(uid).add(String(permission));
    return createAuthSuccess({ granted: true, userId: uid, permission: permission });
  }

  function revokePermission(userId, permission) {
    var uid = String(userId || "");
    var perms = userPermissions.get(uid);
    if (!perms) return createAuthSuccess({ revoked: false });
    var removed = perms.delete(String(permission));
    return createAuthSuccess({ revoked: removed });
  }

  function listPermissions(userId, role) {
    return getEffectivePermissions(userId, role);
  }

  function setUserRole(userId, role) {
    if (!ROLES[role]) {
      return createAuthError("invalid_role", "Role " + role + " is not valid");
    }
    userRoles.set(String(userId), role);
    return createAuthSuccess({ updated: true, role: role });
  }

  function assertPermission(userId, role, permission) {
    if (!check(userId, role, permission)) {
      return createAuthError(AUTH_ERRORS.permissionDenied, "Permission denied: " + permission);
    }
    return createAuthSuccess({ allowed: true });
  }

  function assertRole(userRole, requiredRole) {
    if (!checkRole(userRole, requiredRole)) {
      return createAuthError(AUTH_ERRORS.roleTooLow, "Role '" + userRole + "' is insufficient; requires '" + requiredRole + "'");
    }
    return createAuthSuccess({ allowed: true });
  }

  return {
    check: check,
    checkRole: checkRole,
    checkAll: checkAll,
    checkAny: checkAny,
    grantPermission: grantPermission,
    revokePermission: revokePermission,
    listPermissions: listPermissions,
    setUserRole: setUserRole,
    assertPermission: assertPermission,
    assertRole: assertRole,
    ROLE_PERMISSIONS: BUILT_IN_ROLE_PERMISSIONS,
  };
}

module.exports = { createPermissionManager, BUILT_IN_ROLE_PERMISSIONS };
