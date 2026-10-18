/* ==========================================================================
   TrustMed — Frontend interactivity & API integration
   ========================================================================== */

const API = {
  medicines: "/api/medicines",
  categories: "/api/categories",
  orders: "/api/orders",
  adminMedicines: "/api/admin/medicines",
  blockchain: "/api/blockchain",
  verify: "/api/blockchain/verify",
  tamperDemo: "/api/blockchain/tamper-demo",
  resetDemo: "/api/blockchain/reset-demo",
};

let cart = []; // [{id, name, price, qty}]
let currentMedicines = [];

const inr = (n) =>
  "₹" + Number(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// ---------------------------------------------------------------------------
// Toast helper
// ---------------------------------------------------------------------------

function showToast(message, type = "") {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.className = "toast show " + type;
  setTimeout(() => (toast.className = "toast"), 2600);
}

// ---------------------------------------------------------------------------
// Tab navigation
// ---------------------------------------------------------------------------

document.getElementById("tabNav").addEventListener("click", (e) => {
  const btn = e.target.closest(".tab-btn");
  if (!btn) return;
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  btn.classList.add("active");
  document.getElementById("view-" + btn.dataset.tab).classList.add("active");

  if (btn.dataset.tab === "admin") {
    loadAdminMedicines();
    loadAdminOrders();
  }
  if (btn.dataset.tab === "auditor") {
    loadBlockchain();
  }
});

// ---------------------------------------------------------------------------
// PATIENT MODULE
// ---------------------------------------------------------------------------

async function loadCategories() {
  const res = await fetch(API.categories);
  const categories = await res.json();
  const select = document.getElementById("categoryFilter");
  select.innerHTML = '<option value="all">All Categories</option>' +
    categories.map((c) => `<option value="${c}">${c}</option>`).join("");
}

async function loadMedicines() {
  const search = document.getElementById("searchInput").value.trim();
  const category = document.getElementById("categoryFilter").value;
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  if (category) params.set("category", category);

  const res = await fetch(`${API.medicines}?${params.toString()}`);
  currentMedicines = await res.json();
  renderMedicineGrid();
}

function renderMedicineGrid() {
  const grid = document.getElementById("medicineGrid");
  if (currentMedicines.length === 0) {
    grid.innerHTML = '<p class="empty-state">No medicines match your search.</p>';
    return;
  }

  grid.innerHTML = currentMedicines
    .map((m) => {
      let stockLabel = `${m.stock} in stock`;
      let stockClass = "";
      if (m.stock === 0) { stockLabel = "Out of stock"; stockClass = "out"; }
      else if (m.stock < 20) { stockClass = "low"; }

      return `
        <div class="medicine-card">
          <span class="med-category">${m.category}</span>
          <div class="med-name">${m.name}</div>
          <div class="med-meta">
            <span class="med-price">${inr(m.price)}</span>
            <span class="stock-tag ${stockClass}">${stockLabel}</span>
          </div>
          <div class="med-actions">
            <input type="number" class="qty-input" min="1" max="${m.stock}" value="1" ${m.stock === 0 ? "disabled" : ""} data-qty-for="${m.id}" />
            <button class="btn btn-primary btn-sm" ${m.stock === 0 ? "disabled" : ""} onclick="addToCart(${m.id})">Add to Cart</button>
          </div>
        </div>`;
    })
    .join("");
}

function addToCart(medId) {
  const med = currentMedicines.find((m) => m.id === medId);
  if (!med) return;
  const qtyInput = document.querySelector(`[data-qty-for="${medId}"]`);
  const qty = Math.max(1, parseInt(qtyInput.value || "1", 10));

  if (qty > med.stock) {
    showToast(`Only ${med.stock} units of ${med.name} available`, "error");
    return;
  }

  const existing = cart.find((c) => c.id === medId);
  if (existing) {
    existing.qty = Math.min(existing.qty + qty, med.stock);
  } else {
    cart.push({ id: med.id, name: med.name, price: med.price, qty });
  }
  renderCart();
  showToast(`${med.name} added to cart`, "success");
}

function removeFromCart(medId) {
  cart = cart.filter((c) => c.id !== medId);
  renderCart();
}

function renderCart() {
  const container = document.getElementById("cartItems");
  if (cart.length === 0) {
    container.innerHTML = '<p class="empty-state">Your cart is empty.</p>';
  } else {
    container.innerHTML = cart
      .map(
        (c) => `
        <div class="cart-item">
          <div>
            <div class="cart-item-name">${c.name}</div>
            <div class="cart-item-sub">${c.qty} × ${inr(c.price)} = ${inr(c.qty * c.price)}</div>
          </div>
          <button class="cart-item-remove" onclick="removeFromCart(${c.id})" title="Remove">✕</button>
        </div>`
      )
      .join("");
  }

  const total = cart.reduce((sum, c) => sum + c.qty * c.price, 0);
  document.getElementById("cartTotal").textContent = inr(total);
}

async function placeOrder() {
  if (cart.length === 0) {
    showToast("Add items to your cart first", "error");
    return;
  }
  const customerName = document.getElementById("customerName").value.trim() || "Guest Patient";
  const payload = {
    customer_name: customerName,
    items: cart.map((c) => ({ id: c.id, qty: c.qty })),
  };

  try {
    const res = await fetch(API.orders, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      showToast(data.error || "Failed to place order", "error");
      return;
    }
    showToast(`Order #${data.order.id} placed — mined to Block #${data.block.index}`, "success");
    cart = [];
    renderCart();
    loadMedicines();
    loadPatientOrderHistory();
  } catch (err) {
    showToast("Network error placing order", "error");
  }
}

async function loadPatientOrderHistory() {
  const res = await fetch(API.orders);
  const orders = await res.json();
  const container = document.getElementById("patientOrderHistory");
  if (orders.length === 0) {
    container.innerHTML = '<p class="empty-state">No orders yet.</p>';
    return;
  }
  container.innerHTML = orders
    .slice(0, 10)
    .map(
      (o) => `
      <div class="order-card">
        <div class="order-card-top">
          <span>#${o.id} — ${o.customer_name}</span>
          <span class="status-badge status-${o.status}">${o.status}</span>
        </div>
        <div>${o.items.map((i) => `${i.medicine} ×${i.qty}`).join(", ")}</div>
        <div><strong>${inr(o.total)}</strong></div>
      </div>`
    )
    .join("");
}

document.getElementById("placeOrderBtn").addEventListener("click", placeOrder);
document.getElementById("searchInput").addEventListener("input", debounce(loadMedicines, 250));
document.getElementById("categoryFilter").addEventListener("change", loadMedicines);

function debounce(fn, delay) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

// ---------------------------------------------------------------------------
// ADMIN MODULE
// ---------------------------------------------------------------------------

async function loadAdminMedicines() {
  const res = await fetch(API.adminMedicines);
  const medicines = await res.json();
  const tbody = document.querySelector("#adminMedTable tbody");
  tbody.innerHTML = medicines
    .map(
      (m) => `
      <tr>
        <td>${m.name}</td>
        <td>${m.category}</td>
        <td><input type="number" class="inline-edit" value="${m.stock}" min="0" id="stock-${m.id}" /></td>
        <td><input type="number" class="inline-edit" value="${m.price}" min="0.01" step="0.01" id="price-${m.id}" /></td>
        <td>${m.active ? '<span class="badge-active">Active</span>' : '<span class="badge-inactive">Inactive</span>'}</td>
        <td style="display:flex; gap:6px;">
          <button class="btn btn-outline btn-sm" onclick="updateMedicine(${m.id})">Save</button>
          <button class="btn btn-danger-outline btn-sm" onclick="toggleMedicine(${m.id})">${m.active ? "Deactivate" : "Activate"}</button>
        </td>
      </tr>`
    )
    .join("");
}

async function updateMedicine(id) {
  const stock = document.getElementById(`stock-${id}`).value;
  const price = document.getElementById(`price-${id}`).value;

  const res = await fetch(`${API.adminMedicines}/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ stock, price }),
  });
  const data = await res.json();
  if (!res.ok) {
    showToast(data.error || "Update failed", "error");
    return;
  }
  showToast(`Updated — mined to Block #${data.block.index}`, "success");
  loadAdminMedicines();
}

async function toggleMedicine(id) {
  const res = await fetch(`${API.adminMedicines}/${id}/toggle`, { method: "PUT" });
  const data = await res.json();
  if (!res.ok) {
    showToast(data.error || "Update failed", "error");
    return;
  }
  showToast(`Listing status changed — mined to Block #${data.block.index}`, "success");
  loadAdminMedicines();
}

document.getElementById("addMedicineForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    name: document.getElementById("newMedName").value.trim(),
    category: document.getElementById("newMedCategory").value.trim(),
    stock: document.getElementById("newMedStock").value,
    price: document.getElementById("newMedPrice").value,
  };

  const res = await fetch(API.adminMedicines, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    showToast(data.error || "Failed to add medicine", "error");
    return;
  }
  showToast(`${data.medicine.name} added — mined to Block #${data.block.index}`, "success");
  e.target.reset();
  loadAdminMedicines();
});

async function loadAdminOrders() {
  const res = await fetch(API.orders);
  const orders = await res.json();
  const tbody = document.querySelector("#adminOrderTable tbody");
  const statuses = ["Placed", "Processing", "Shipped", "Delivered", "Cancelled"];

  tbody.innerHTML = orders
    .map(
      (o) => `
      <tr>
        <td>#${o.id}</td>
        <td>${o.customer_name}</td>
        <td>${o.items.map((i) => `${i.medicine} ×${i.qty}`).join(", ")}</td>
        <td>${inr(o.total)}</td>
        <td><span class="status-badge status-${o.status}">${o.status}</span></td>
        <td>
          <select id="status-${o.id}" class="inline-edit" style="width:auto;">
            ${statuses.map((s) => `<option value="${s}" ${s === o.status ? "selected" : ""}>${s}</option>`).join("")}
          </select>
          <button class="btn btn-outline btn-sm" onclick="updateOrderStatus(${o.id})">Update</button>
        </td>
      </tr>`
    )
    .join("");
}

async function updateOrderStatus(orderId) {
  const status = document.getElementById(`status-${orderId}`).value;
  const res = await fetch(`${API.orders}/${orderId}/status`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  const data = await res.json();
  if (!res.ok) {
    showToast(data.error || "Failed to update status", "error");
    return;
  }
  showToast(`Order #${orderId} → ${status} — mined to Block #${data.block.index}`, "success");
  loadAdminOrders();
}

// ---------------------------------------------------------------------------
// AUDITOR MODULE
// ---------------------------------------------------------------------------

async function loadBlockchain() {
  const res = await fetch(API.blockchain);
  const chain = await res.json();
  renderChain(chain);
}

function renderChain(chain, validityMap = null) {
  const explorer = document.getElementById("chainExplorer");
  explorer.innerHTML = chain
    .slice()
    .reverse()
    .map((block) => {
      const validity = validityMap ? validityMap[block.index] : null;
      const tampered = validity && !validity.block_valid;
      return `
        <div class="block-card ${tampered ? "tampered" : ""}">
          <div class="block-head">
            <span class="block-index-tag">
              <span class="block-index-num">${block.index}</span>
              Block #${block.index}
              <span class="event-type-badge">${block.event_type}</span>
            </span>
            <span class="block-timestamp">${new Date(block.timestamp).toLocaleString("en-IN")}</span>
            ${validity ? `<span class="block-valid-tag ${validity.block_valid ? "ok" : "bad"}">${validity.block_valid ? "✔ Verified" : "✖ Tampered"}</span>` : ""}
          </div>
          <div class="block-hash-row"><span class="label">Hash:</span> ${block.hash}</div>
          <div class="block-hash-row"><span class="label">Prev:</span> ${block.previous_hash}</div>
          <div class="block-payload">${JSON.stringify(block.payload, null, 2)}</div>
        </div>`;
    })
    .join("");
}

async function verifyLedger() {
  const res = await fetch(API.verify);
  const result = await res.json();

  const validityMap = {};
  result.report.forEach((r) => (validityMap[r.index] = r));

  const chainRes = await fetch(API.blockchain);
  const chain = await chainRes.json();
  renderChain(chain, validityMap);

  const resultBox = document.getElementById("verifyResult");
  const dot = document.getElementById("chainDot");
  const statusText = document.getElementById("chainStatusText");

  if (result.valid) {
    resultBox.innerHTML = `<div class="verify-banner valid">✔ Ledger integrity verified — all ${result.blocks_checked} blocks are consistent and immutable.</div>`;
    dot.classList.remove("invalid");
    statusText.textContent = "Ledger verified";
  } else {
    const badBlocks = result.report.filter((r) => !r.block_valid).map((r) => r.index).join(", ");
    resultBox.innerHTML = `<div class="verify-banner invalid">✖ Integrity check FAILED — tampering detected at block(s): ${badBlocks}.</div>`;
    dot.classList.add("invalid");
    statusText.textContent = "Tampering detected";
  }
}

async function tamperDemo() {
  const res = await fetch(API.blockchain);
  const chain = await res.json();
  const nonGenesis = chain.filter((b) => b.event_type !== "GENESIS");
  if (nonGenesis.length === 0) {
    showToast("No tamperable blocks yet", "error");
    return;
  }
  const target = nonGenesis[nonGenesis.length - 1];

  const tRes = await fetch(API.tamperDemo, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ index: target.index }),
  });
  const data = await tRes.json();
  if (!tRes.ok) {
    showToast(data.error || "Tamper demo failed", "error");
    return;
  }
  showToast(`Simulated tampering on Block #${target.index} — click "Verify Ledger Integrity"`, "error");
  loadBlockchain();
}

async function resetLedger() {
  const res = await fetch(API.resetDemo, { method: "POST" });
  if (!res.ok) {
    showToast("Failed to reset ledger", "error");
    return;
  }
  showToast("Ledger rebuilt from genesis", "success");
  document.getElementById("verifyResult").innerHTML = "";
  document.getElementById("chainDot").classList.remove("invalid");
  document.getElementById("chainStatusText").textContent = "Ledger synced";
  loadBlockchain();
}

document.getElementById("verifyLedgerBtn").addEventListener("click", verifyLedger);
document.getElementById("tamperDemoBtn").addEventListener("click", tamperDemo);
document.getElementById("resetLedgerBtn").addEventListener("click", resetLedger);

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

(async function init() {
  await loadCategories();
  await loadMedicines();
  await loadPatientOrderHistory();
})();
