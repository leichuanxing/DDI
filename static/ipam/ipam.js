(function () {
  const csrfToken = document.querySelector("meta[name='csrf-token']")?.getAttribute("content") || "";

  async function postForm(url, formData) {
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "X-CSRFToken": csrfToken,
        "Accept": "application/json",
      },
      body: formData,
    });
    const data = await response.json().catch(function () { return {}; });
    if (!response.ok || data.success === false) {
      throw new Error(data.message || "操作失败");
    }
    return data;
  }

  const allocateModal = document.getElementById("ipAllocateModal");
  const allocateForm = document.getElementById("ipAllocateForm");
  let allocateUrl = "";

  document.querySelectorAll("[data-ipam-allocate]").forEach(function (button) {
    button.addEventListener("click", function () {
      var customUrl = button.dataset.allocateUrl || "";
      allocateUrl = customUrl || ("/ipam/ips/" + button.dataset.id + "/allocate/");
      if (allocateForm) allocateForm.reset();
      var ipInput = document.getElementById("allocateIpAddress");
      var snInput = document.getElementById("allocateSubnet");
      if (ipInput) ipInput.value = button.dataset.ip || "";
      if (snInput) snInput.value = button.dataset.subnet || "";
      var hiddenIp = document.getElementById("allocateIpAddressHidden");
      if (hiddenIp) {
        if (customUrl) {
          hiddenIp.removeAttribute("disabled");
          hiddenIp.value = button.dataset.ip || "";
        } else {
          hiddenIp.setAttribute("disabled", "disabled");
          hiddenIp.value = "";
        }
      }
      var macField = allocateForm ? allocateForm.querySelector('input[name="mac_address"]') : null;
      if (macField) macField.value = button.dataset.mac || "";
      if (allocateModal) allocateModal.hidden = false;
    });
  });

  document.querySelectorAll("[data-ipam-allocate-cancel]").forEach(function (button) {
    button.addEventListener("click", function () {
      if (allocateModal) allocateModal.hidden = true;
    });
  });

  if (allocateForm) {
    allocateForm.addEventListener("submit", async function (event) {
      event.preventDefault();
      const submit = allocateForm.querySelector("button[type='submit']");
      const oldText = submit.textContent;
      submit.disabled = true;
      submit.textContent = "处理中...";
      try {
        await postForm(allocateUrl, new FormData(allocateForm));
        window.ddiToast("IP 分配成功。", "success");
        if (allocateModal) allocateModal.hidden = true;
        setTimeout(function () { window.location.reload(); }, 700);
      } catch (error) {
        window.ddiToast(error.message, "error");
      } finally {
        submit.disabled = false;
        submit.textContent = oldText;
      }
    });
  }

  document.querySelectorAll("[data-ipam-ping-url]").forEach(function (button) {
    button.addEventListener("click", async function () {
      const oldText = button.textContent;
      button.disabled = true;
      button.textContent = "探测中...";
      try {
        const response = await fetch(button.dataset.ipamPingUrl, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "X-CSRFToken": csrfToken,
            "Accept": "application/json",
          },
        });
        const data = await response.json().catch(function () { return {}; });
        if (!response.ok || data.success === false) {
          throw new Error(data.message || "探测失败");
        }
        window.ddiToast("探测完成：" + (data.data?.status || "unknown"), "success");
        setTimeout(function () { window.location.reload(); }, 700);
      } catch (error) {
        window.ddiToast(error.message, "error");
      } finally {
        button.disabled = false;
        button.textContent = oldText;
      }
    });
  });

  document.querySelectorAll("[data-ipam-quick-ping], [data-ipam-subnet-scan]").forEach(function (form) {
    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      const submit = form.querySelector("button[type='submit']");
      const oldText = submit.textContent;
      submit.disabled = true;
      submit.textContent = "处理中...";
      try {
        const data = await postForm(form.action, new FormData(form));
        window.ddiToast(data.message || "操作成功", "success");
        setTimeout(function () { window.location.reload(); }, 700);
      } catch (error) {
        window.ddiToast(error.message, "error");
      } finally {
        submit.disabled = false;
        submit.textContent = oldText;
      }
    });
  });
})();
