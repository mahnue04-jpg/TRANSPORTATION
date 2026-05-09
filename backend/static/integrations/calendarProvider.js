"use strict";

/**
 * calendarProvider.js — Calendar provider abstraction.
 * Plug in Google Calendar, Outlook, CalDAV, etc.
 */

const {
  INTEGRATION_TYPES,
  INTEGRATION_ERRORS,
  uid,
  clone,
  createIntegrationError,
  createIntegrationSuccess,
} = require("./integrationSchemas");

const RECURRENCE = { none: "none", daily: "daily", weekly: "weekly", monthly: "monthly", yearly: "yearly" };
const EVENT_STATUS = { tentative: "tentative", confirmed: "confirmed", cancelled: "cancelled" };

function createCalendarEvent(options) {
  var opts = options || {};
  return {
    id:          opts.id || uid("evt"),
    calendarId:  opts.calendarId || "default",
    title:       opts.title || "Untitled",
    description: opts.description || "",
    startAt:     opts.startAt || Date.now(),
    endAt:       opts.endAt || (Date.now() + 3600000),
    allDay:      opts.allDay || false,
    location:    opts.location || null,
    attendees:   clone(opts.attendees || []),
    recurrence:  opts.recurrence || RECURRENCE.none,
    status:      opts.status || EVENT_STATUS.confirmed,
    metadata:    clone(opts.metadata || {}),
    createdAt:   Date.now(),
    updatedAt:   Date.now(),
  };
}

function createCalendarProvider(options) {
  var config = Object.assign(
    {
      provider: null,  // async adapter: { createEvent, getEvent, updateEvent, deleteEvent, listEvents, [healthCheck] }
      userId:   null,
    },
    options || {}
  );

  // In-memory store (mock/offline mode)
  var eventStore = new Map();

  function validateEvent(opts) {
    if (!opts.title || !String(opts.title).trim()) return { ok: false, message: "Title is required" };
    if (opts.startAt && opts.endAt && opts.endAt < opts.startAt) {
      return { ok: false, message: "endAt must be after startAt" };
    }
    return { ok: true };
  }

  async function createEvent(options) {
    var validation = validateEvent(options || {});
    if (!validation.ok) return createIntegrationError(INTEGRATION_ERRORS.invalidConfig, validation.message);

    if (config.provider) {
      try {
        var result = await config.provider.createEvent(options);
        if (result && result.ok === false) return createIntegrationError(INTEGRATION_ERRORS.providerError, result.message);
        return createIntegrationSuccess({ event: result.event || result });
      } catch (err) {
        return createIntegrationError(INTEGRATION_ERRORS.providerError, (err && err.message) || "createEvent failed");
      }
    }

    var evt = createCalendarEvent(options);
    eventStore.set(evt.id, evt);
    return createIntegrationSuccess({ event: clone(evt) });
  }

  async function getEvent(eventId) {
    if (config.provider) {
      try {
        var result = await config.provider.getEvent(eventId);
        if (result && result.ok === false) return createIntegrationError(INTEGRATION_ERRORS.notFound, result.message);
        return createIntegrationSuccess({ event: result.event || result });
      } catch (err) {
        return createIntegrationError(INTEGRATION_ERRORS.providerError, (err && err.message) || "getEvent failed");
      }
    }
    var evt = eventStore.get(eventId);
    if (!evt) return createIntegrationError(INTEGRATION_ERRORS.notFound, "Event not found: " + eventId);
    return createIntegrationSuccess({ event: clone(evt) });
  }

  async function updateEvent(eventId, patch) {
    if (config.provider) {
      try {
        var result = await config.provider.updateEvent(eventId, patch);
        if (result && result.ok === false) return createIntegrationError(INTEGRATION_ERRORS.providerError, result.message);
        return createIntegrationSuccess({ event: result.event || result });
      } catch (err) {
        return createIntegrationError(INTEGRATION_ERRORS.providerError, (err && err.message) || "updateEvent failed");
      }
    }
    var evt = eventStore.get(eventId);
    if (!evt) return createIntegrationError(INTEGRATION_ERRORS.notFound, "Event not found: " + eventId);
    Object.assign(evt, patch, { id: eventId, updatedAt: Date.now() });
    return createIntegrationSuccess({ event: clone(evt) });
  }

  async function deleteEvent(eventId) {
    if (config.provider) {
      try {
        var result = await config.provider.deleteEvent(eventId);
        if (result && result.ok === false) return createIntegrationError(INTEGRATION_ERRORS.providerError, result.message);
        return createIntegrationSuccess({ eventId });
      } catch (err) {
        return createIntegrationError(INTEGRATION_ERRORS.providerError, (err && err.message) || "deleteEvent failed");
      }
    }
    if (!eventStore.has(eventId)) return createIntegrationError(INTEGRATION_ERRORS.notFound, "Event not found: " + eventId);
    eventStore.delete(eventId);
    return createIntegrationSuccess({ eventId });
  }

  async function listEvents(filters) {
    if (config.provider) {
      try {
        var result = await config.provider.listEvents(filters);
        if (result && result.ok === false) return createIntegrationError(INTEGRATION_ERRORS.providerError, result.message);
        return createIntegrationSuccess({ events: result.events || [] });
      } catch (err) {
        return createIntegrationError(INTEGRATION_ERRORS.providerError, (err && err.message) || "listEvents failed");
      }
    }
    var opts = filters || {};
    var events = Array.from(eventStore.values());
    if (opts.startAt) events = events.filter(function (e) { return e.endAt >= opts.startAt; });
    if (opts.endAt)   events = events.filter(function (e) { return e.startAt <= opts.endAt; });
    if (opts.calendarId) events = events.filter(function (e) { return e.calendarId === opts.calendarId; });
    events.sort(function (a, b) { return a.startAt - b.startAt; });
    return createIntegrationSuccess({ events: events.map(clone) });
  }

  async function healthCheck() {
    if (config.provider && typeof config.provider.healthCheck === "function") {
      try {
        var r = await config.provider.healthCheck();
        return createIntegrationSuccess({ healthy: !r || r.ok !== false });
      } catch (_) {
        return createIntegrationSuccess({ healthy: false });
      }
    }
    return createIntegrationSuccess({ healthy: true });
  }

  return {
    name:         "calendar",
    type:         INTEGRATION_TYPES.calendar,
    capabilities: ["createEvent", "getEvent", "updateEvent", "deleteEvent", "listEvents", "healthCheck"],
    RECURRENCE,
    EVENT_STATUS,
    createEvent,
    getEvent,
    updateEvent,
    deleteEvent,
    listEvents,
    healthCheck,
  };
}

module.exports = { createCalendarProvider, RECURRENCE, EVENT_STATUS };
