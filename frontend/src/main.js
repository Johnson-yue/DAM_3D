import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import Library from './views/Library.vue'
import Preview from './views/Preview.vue'
import SearchView from './views/SearchView.vue'
import Settings from './views/Settings.vue'
import './style.css'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: Library },
    { path: '/preview/:id', component: Preview },
    { path: '/search', component: SearchView },
    { path: '/settings', component: Settings },
  ],
})

createApp(App).use(router).mount('#app')
