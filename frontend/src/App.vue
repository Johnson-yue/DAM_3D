<template>
  <div class="shell">
    <header class="top">
      <div class="brand">DAM 3D Render</div>
      <nav>
        <router-link to="/">资产库</router-link>
        <router-link to="/search">检索</router-link>
        <router-link to="/settings">设置</router-link>
      </nav>
    </header>
    <main>
      <router-view />
    </main>
  </div>
</template>

<script setup>
</script>

<style scoped>
.shell { max-width: 1280px; margin: 0 auto; padding: 1rem 1.25rem 3rem; }
.top {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 1.25rem; padding-bottom: 0.75rem; border-bottom: 1px solid var(--border);
}
.brand { font-size: 1.25rem; font-weight: 700; letter-spacing: 0.02em; }
nav { display: flex; gap: 1rem; }
nav a { color: var(--muted); }
nav a.router-link-active { color: var(--text); font-weight: 600; }
</style>
