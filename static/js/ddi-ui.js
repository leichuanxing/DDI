(function () {
  const body = document.body;
  const toggle = document.querySelector("[data-sidebar-toggle]");
  if (toggle) {
    toggle.addEventListener("click", function () {
      if (window.matchMedia("(max-width: 760px)").matches) {
        body.classList.toggle("sidebar-open");
      } else {
        body.classList.toggle("sidebar-collapsed");
        localStorage.setItem("ddi.sidebarCollapsed", body.classList.contains("sidebar-collapsed") ? "1" : "0");
      }
    });
  }
  if (localStorage.getItem("ddi.sidebarCollapsed") === "1") body.classList.add("sidebar-collapsed");

  document.querySelectorAll(".side-group-title").forEach(function (btn) {
    btn.addEventListener("click", function () {
      btn.closest(".side-group").classList.toggle("open");
    });
  });

  document.querySelectorAll("[data-row-select], [data-select-all]").forEach(function (box) {
    box.addEventListener("change", function () {
      if (box.matches("[data-select-all]")) {
        document.querySelectorAll("[data-row-select]").forEach(function (item) { item.checked = box.checked; });
      }
      const total = document.querySelectorAll("[data-row-select]:checked").length;
      document.querySelectorAll("[data-selected-count]").forEach(function (node) {
        node.textContent = total ? "已选择 " + total + " 项" : "未选择数据";
      });
    });
  });

  const modal = document.getElementById("confirmModal");
  let pendingAction = null;
  const csrfToken = document.querySelector("meta[name='csrf-token']")?.getAttribute("content") || "";
  document.querySelectorAll("[data-confirm]").forEach(function (btn) {
    btn.addEventListener("click", function (event) {
      event.preventDefault();
      pendingAction = btn;
      const text = btn.getAttribute("data-confirm") || "该操作需要二次确认。";
      const textNode = document.getElementById("confirmText");
      if (textNode) textNode.textContent = text;
      if (modal) modal.hidden = false;
    });
  });
  document.querySelectorAll("[data-confirm-cancel]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (modal) modal.hidden = true;
      pendingAction = null;
    });
  });
  document.querySelectorAll("[data-confirm-ok]").forEach(function (btn) {
    btn.addEventListener("click", async function () {
      if (modal) modal.hidden = true;
      if (pendingAction && pendingAction.dataset.confirmUrl) {
        const oldText = btn.textContent;
        btn.disabled = true;
        btn.textContent = "处理中...";
        try {
          const method = (pendingAction.dataset.confirmMethod || "POST").toUpperCase();
          const response = await fetch(pendingAction.dataset.confirmUrl, {
            method: method,
            credentials: "same-origin",
            headers: {
              "Accept": "application/json",
              "Content-Type": "application/json",
              "X-CSRFToken": csrfToken
            },
            body: method === "GET" ? undefined : "{}"
          });
          const data = await response.json().catch(function () { return {}; });
          if (!response.ok || data.success === false) {
            window.ddiToast(data.message || "操作失败，请查看系统日志。", "error");
          } else {
            window.ddiToast(pendingAction.dataset.confirmSuccess || data.message || "操作成功", "success");
            if (pendingAction.dataset.confirmReload !== "false") {
              setTimeout(function () { window.location.reload(); }, 900);
            }
          }
        } catch (error) {
          window.ddiToast(error.message || "请求失败，请检查网络连接。", "error");
        } finally {
          btn.disabled = false;
          btn.textContent = oldText;
        }
      } else if (pendingAction && pendingAction.href) {
        window.location.href = pendingAction.href;
      } else {
        window.ddiToast("该操作尚未配置执行入口。", "info");
      }
      pendingAction = null;
    });
  });

  document.querySelectorAll("[data-toast]").forEach(function (btn) {
    btn.addEventListener("click", function (event) {
      event.preventDefault();
      window.ddiToast(btn.dataset.toast || "功能正在接入中。", "info");
    });
  });

  document.querySelectorAll("a[href='#']").forEach(function (link) {
    link.addEventListener("click", function (event) {
      event.preventDefault();
      window.ddiToast("该入口尚未配置目标地址。", "info");
    });
  });

  document.querySelectorAll("[data-health-check-url]").forEach(function (btn) {
    btn.addEventListener("click", async function () {
      const oldText = btn.textContent;
      btn.disabled = true;
      btn.textContent = "检测中...";
      try {
        const response = await fetch(btn.dataset.healthCheckUrl, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken
          },
          body: "{}"
        });
        const data = await response.json().catch(function () { return {}; });
        if (!response.ok || data.success === false) {
          window.ddiToast(data.message || "健康检查失败，请查看错误详情。", "error");
        } else {
          window.ddiToast("健康检查已完成", "success");
          setTimeout(function () { window.location.reload(); }, 900);
        }
      } catch (error) {
        window.ddiToast(error.message || "健康检查请求失败。", "error");
      } finally {
        btn.disabled = false;
        btn.textContent = oldText;
      }
    });
  });

  document.querySelectorAll("[data-action-url]").forEach(function (btn) {
    btn.addEventListener("click", async function () {
      const oldText = btn.textContent;
      btn.disabled = true;
      btn.textContent = "处理中...";
      try {
        const response = await fetch(btn.dataset.actionUrl, {
          method: btn.dataset.actionMethod || "POST",
          credentials: "same-origin",
          headers: {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken
          },
          body: "{}"
        });
        const data = await response.json().catch(function () { return {}; });
        if (!response.ok || data.success === false) {
          window.ddiToast(data.message || "操作失败，请查看任务日志。", "error");
        } else {
          window.ddiToast(btn.dataset.actionSuccess || data.message || "任务已创建", "success");
          setTimeout(function () { window.location.reload(); }, 900);
        }
      } catch (error) {
        window.ddiToast(error.message || "请求失败。", "error");
      } finally {
        btn.disabled = false;
        btn.textContent = oldText;
      }
    });
  });

  document.querySelectorAll("[data-bulk-delete-url]").forEach(function (btn) {
    btn.addEventListener("click", async function () {
      const ids = Array.from(document.querySelectorAll("[data-row-select]:checked")).map(function (item) {
        return item.value;
      });
      if (!ids.length) {
        window.ddiToast("请先选择需要删除的记录。", "info");
        return;
      }
      if (!window.confirm("确认删除选中的 " + ids.length + " 条记录？该操作会同步删除 PowerDNS 记录。")) {
        return;
      }
      const oldText = btn.textContent;
      btn.disabled = true;
      btn.textContent = "删除中...";
      try {
        const response = await fetch(btn.dataset.bulkDeleteUrl, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken
          },
          body: JSON.stringify({ ids: ids })
        });
        const data = await response.json().catch(function () { return {}; });
        if (!response.ok || data.success === false) {
          window.ddiToast(data.message || "批量删除失败，请查看错误详情。", "error");
        } else {
          const deleted = data.data && typeof data.data.deleted !== "undefined" ? data.data.deleted : ids.length;
          window.ddiToast("已删除 " + deleted + " 条 DNS 记录", "success");
          setTimeout(function () { window.location.reload(); }, 900);
        }
      } catch (error) {
        window.ddiToast(error.message || "批量删除请求失败。", "error");
      } finally {
        btn.disabled = false;
        btn.textContent = oldText;
      }
    });
  });

  document.querySelectorAll("form").forEach(function (form) {
    form.addEventListener("submit", function () {
      const submit = form.querySelector("button[type='submit']");
      if (submit) {
        submit.disabled = true;
        submit.dataset.oldText = submit.textContent;
        submit.textContent = "处理中...";
      }
    });
  });

  window.ddiToast = function (message, type) {
    const stack = document.getElementById("toastStack");
    if (!stack) return;
    const node = document.createElement("div");
    node.className = "toast-message toast-" + (type || "info");
    node.textContent = message;
    stack.appendChild(node);
    setTimeout(function () { node.remove(); }, 3600);
  };

  setTimeout(function () {
    document.querySelectorAll(".toast-message").forEach(function (node) { node.remove(); });
  }, 4200);
})();
