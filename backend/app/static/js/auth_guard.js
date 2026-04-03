(() => {
  const pageRole = document.body?.dataset?.requiredRole;
  if (!pageRole) return;

  const redirectTo = (url) => {
    window.location.href = url;
  };

  const enforce = async () => {
    try {
      const res = await fetch("/api/auth/redirect");
      if (!res.ok) {
        redirectTo("/login");
        return;
      }
      const data = await res.json().catch(() => ({}));
      const redirect = data.redirect || "/login";
      document.querySelectorAll("[data-role-link]").forEach((el) => {
        const required = el.getAttribute("data-role-link");
        if (!required) return;
        if (
          (required === "ADMIN" && redirect !== "/admin") ||
          (required === "USER" && redirect !== "/user")
        ) {
          el.remove();
        }
      });
      if (pageRole === "AUTHENTICATED") {
        return;
      }
      if (pageRole === "ADMIN" && redirect !== "/admin") {
        redirectTo(redirect);
        return;
      }
      if (pageRole === "USER" && redirect !== "/user") {
        redirectTo(redirect);
      }
    } catch (err) {
      redirectTo("/login");
    }
  };

  enforce();
})();
