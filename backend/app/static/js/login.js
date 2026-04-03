document.getElementById("btn").addEventListener("click", async () => {
  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value.trim();
  const msg = document.getElementById("msg");
  msg.textContent = "";

  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });

    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      msg.textContent = data.detail || "Login failed";
      return;
    }

    // store user
    localStorage.setItem("user_email", data.user?.email || "");
    localStorage.setItem("user_role", data.user?.role || "USER");
    localStorage.setItem("user_full_name", data.user?.full_name || "");

    // redirect
    window.location.href = data.redirect || "/user";
  } catch (e) {
    msg.textContent = "Erreur réseau / serveur.";
  }
});
