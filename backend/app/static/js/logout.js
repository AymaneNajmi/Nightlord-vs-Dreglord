(() => {
  const clearClientAuth = () => {
    document.cookie = "access_token=; Path=/; Max-Age=0";
    localStorage.removeItem("access_token");
    localStorage.removeItem("user_full_name");
    localStorage.removeItem("user_email");
    localStorage.removeItem("user_role");
    localStorage.removeItem("user_flow");
  };

  const attachLogout = () => {
    const btns = document.querySelectorAll("[data-logout]");
    if (!btns.length) return;

    btns.forEach((btn) => {
      btn.addEventListener("click", async (event) => {
        event.preventDefault();
        try {
          await fetch("/api/auth/logout", { method: "POST" });
        } catch (err) {
          // ignore network issues
        } finally {
          clearClientAuth();
          window.location.href = "/login";
        }
      });
    });
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", attachLogout);
  } else {
    attachLogout();
  }
})();
