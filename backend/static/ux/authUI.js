"use strict";
/**
 * authUI.js — MVP authentication UI (signup/login/logout).
 *
 * Provides:
 * - Signup screen overlay
 * - Login screen overlay
 * - Session validation UI integration
 *
 * Exported: window.AmiCorAuthUI / module.exports
 */

(function(global) {

function injectStyles() {
  if (document.getElementById("amicor-auth-styles")) return;
  const style = document.createElement("style");
  style.id = "amicor-auth-styles";
  style.textContent = `
    #amicor-auth-overlay {
      position: fixed; top: 0; left: 0; width: 100%; height: 100%;
      background: rgba(0, 0, 0, 0.6);
      display: flex; align-items: center; justify-content: center;
      z-index: 9999;
    }
    .amicor-auth-modal {
      background: white;
      border-radius: 12px;
      padding: 32px;
      max-width: 400px;
      width: 90%;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
    }
    .amicor-auth-modal h2 {
      margin: 0 0 24px 0;
      font-size: 24px;
      color: #1a1a1a;
    }
    .amicor-auth-modal p {
      margin: 0 0 16px 0;
      color: #666;
      font-size: 14px;
    }
    .amicor-auth-form {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .amicor-auth-input {
      padding: 10px 12px;
      border: 1px solid #ddd;
      border-radius: 6px;
      font-size: 14px;
      font-family: inherit;
    }
    .amicor-auth-input:focus {
      outline: none;
      border-color: #0066cc;
      box-shadow: 0 0 0 3px rgba(0, 102, 204, 0.1);
    }
    .amicor-auth-buttons {
      display: flex;
      gap: 12px;
      margin-top: 16px;
    }
    .amicor-auth-btn {
      flex: 1;
      padding: 10px 16px;
      border: none;
      border-radius: 6px;
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
      transition: all 200ms;
    }
    .amicor-auth-btn-primary {
      background: #0066cc;
      color: white;
    }
    .amicor-auth-btn-primary:hover {
      background: #0052a3;
    }
    .amicor-auth-btn-secondary {
      background: #f0f0f0;
      color: #333;
    }
    .amicor-auth-btn-secondary:hover {
      background: #e0e0e0;
    }
    .amicor-auth-toggle {
      text-align: center;
      margin-top: 16px;
      font-size: 14px;
      color: #666;
    }
    .amicor-auth-toggle a {
      color: #0066cc;
      cursor: pointer;
      text-decoration: none;
    }
    .amicor-auth-toggle a:hover {
      text-decoration: underline;
    }
    .amicor-auth-error {
      background: #fee;
      border: 1px solid #fcc;
      color: #c00;
      padding: 10px 12px;
      border-radius: 6px;
      font-size: 13px;
      margin-bottom: 12px;
    }
  `;
  document.head.appendChild(style);
}

function createSignupModal(onSignup, onToggleLogin) {
  const overlay = document.createElement("div");
  overlay.id = "amicor-auth-overlay";
  
  const modal = document.createElement("div");
  modal.className = "amicor-auth-modal";
  
  let errorMsg = "";
  
  modal.innerHTML = `
    <h2>Sign Up</h2>
    <p>Create your Amicor account</p>
    <div class="amicor-auth-error" style="display:none;"></div>
    <form class="amicor-auth-form">
      <input type="text" class="amicor-auth-input" placeholder="Full name" required>
      <input type="email" class="amicor-auth-input" placeholder="Email" required>
      <input type="password" class="amicor-auth-input" placeholder="Password (min 6 chars)" required>
      <div class="amicor-auth-buttons">
        <button type="submit" class="amicor-auth-btn amicor-auth-btn-primary">Sign Up</button>
        <button type="button" class="amicor-auth-btn amicor-auth-btn-secondary">Cancel</button>
      </div>
    </form>
    <div class="amicor-auth-toggle">
      Already have an account? <a>Log In</a>
    </div>
  `;
  
  const form = modal.querySelector("form");
  const inputs = modal.querySelectorAll(".amicor-auth-input");
  const errorDiv = modal.querySelector(".amicor-auth-error");
  const cancelBtn = modal.querySelector("button[type='button']");
  const toggleLink = modal.querySelector(".amicor-auth-toggle a");
  
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const name = inputs[0].value.trim();
    const email = inputs[1].value.trim();
    const password = inputs[2].value.trim();
    
    if (!name || !email || !password) {
      errorDiv.textContent = "All fields required";
      errorDiv.style.display = "block";
      return;
    }
    if (password.length < 6) {
      errorDiv.textContent = "Password must be at least 6 characters";
      errorDiv.style.display = "block";
      return;
    }
    
    overlay.remove();
    onSignup({ name, email });
  });
  
  cancelBtn.addEventListener("click", () => {
    overlay.remove();
  });
  
  toggleLink.addEventListener("click", (e) => {
    e.preventDefault();
    overlay.remove();
    onToggleLogin();
  });
  
  overlay.appendChild(modal);
  return overlay;
}

function createLoginModal(onLogin, onToggleSignup) {
  const overlay = document.createElement("div");
  overlay.id = "amicor-auth-overlay";
  
  const modal = document.createElement("div");
  modal.className = "amicor-auth-modal";
  
  modal.innerHTML = `
    <h2>Log In</h2>
    <p>Welcome back to Amicor</p>
    <div class="amicor-auth-error" style="display:none;"></div>
    <form class="amicor-auth-form">
      <input type="email" class="amicor-auth-input" placeholder="Email" required>
      <input type="password" class="amicor-auth-input" placeholder="Password" required>
      <div class="amicor-auth-buttons">
        <button type="submit" class="amicor-auth-btn amicor-auth-btn-primary">Log In</button>
        <button type="button" class="amicor-auth-btn amicor-auth-btn-secondary">Cancel</button>
      </div>
    </form>
    <div class="amicor-auth-toggle">
      Don't have an account? <a>Sign Up</a>
    </div>
  `;
  
  const form = modal.querySelector("form");
  const inputs = modal.querySelectorAll(".amicor-auth-input");
  const errorDiv = modal.querySelector(".amicor-auth-error");
  const cancelBtn = modal.querySelector("button[type='button']");
  const toggleLink = modal.querySelector(".amicor-auth-toggle a");
  
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const email = inputs[0].value.trim();
    const password = inputs[1].value.trim();
    
    if (!email || !password) {
      errorDiv.textContent = "Email and password required";
      errorDiv.style.display = "block";
      return;
    }
    
    overlay.remove();
    // For MVP: accept any email + password combo (no real auth backend)
    onLogin({ email, name: email.split("@")[0] });
  });
  
  cancelBtn.addEventListener("click", () => {
    overlay.remove();
  });
  
  toggleLink.addEventListener("click", (e) => {
    e.preventDefault();
    overlay.remove();
    onToggleSignup();
  });
  
  overlay.appendChild(modal);
  return overlay;
}

const AmiCorAuthUI = {
  showSignup(onSignup, onToggleLogin) {
    injectStyles();
    const modal = createSignupModal(onSignup, onToggleLogin);
    document.body.appendChild(modal);
  },
  
  showLogin(onLogin, onToggleSignup) {
    injectStyles();
    const modal = createLoginModal(onLogin, onToggleSignup);
    document.body.appendChild(modal);
  },
};

// ── Export ───────────────────────────────────────────────────────────────

if (typeof window !== "undefined") {
  window.AmiCorAuthUI = AmiCorAuthUI;
}
if (typeof module !== "undefined" && module.exports) {
  module.exports = AmiCorAuthUI;
}

}(typeof window !== "undefined" ? window : global));
