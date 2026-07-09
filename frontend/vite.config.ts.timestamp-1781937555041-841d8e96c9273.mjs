// vite.config.ts
import { defineConfig } from "file:///D:/%E5%B7%A5%E4%B8%9A%E5%85%83/%E6%95%B0%E4%BA%91_%E6%96%B0%E8%B4%A8%E5%8A%9B/ziwi_project_SaaS/code/frontend/node_modules/vite/dist/node/index.js";
import vue from "file:///D:/%E5%B7%A5%E4%B8%9A%E5%85%83/%E6%95%B0%E4%BA%91_%E6%96%B0%E8%B4%A8%E5%8A%9B/ziwi_project_SaaS/code/frontend/node_modules/@vitejs/plugin-vue/dist/index.mjs";
import Components from "file:///D:/%E5%B7%A5%E4%B8%9A%E5%85%83/%E6%95%B0%E4%BA%91_%E6%96%B0%E8%B4%A8%E5%8A%9B/ziwi_project_SaaS/code/frontend/node_modules/unplugin-vue-components/dist/vite.js";
import { VantResolver } from "file:///D:/%E5%B7%A5%E4%B8%9A%E5%85%83/%E6%95%B0%E4%BA%91_%E6%96%B0%E8%B4%A8%E5%8A%9B/ziwi_project_SaaS/code/frontend/node_modules/@vant/auto-import-resolver/dist/index.js";
var vite_config_default = defineConfig({
  plugins: [
    vue(),
    Components({
      resolvers: [VantResolver()]
    })
  ],
  server: {
    port: 5173,
    host: "0.0.0.0",
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true
      }
    }
  },
  resolve: {
    alias: {
      "@": "/src"
    }
  }
});
export {
  vite_config_default as default
};
//# sourceMappingURL=data:application/json;base64,ewogICJ2ZXJzaW9uIjogMywKICAic291cmNlcyI6IFsidml0ZS5jb25maWcudHMiXSwKICAic291cmNlc0NvbnRlbnQiOiBbImNvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9kaXJuYW1lID0gXCJEOlxcXFxcdTVERTVcdTRFMUFcdTUxNDNcXFxcXHU2NTcwXHU0RTkxX1x1NjVCMFx1OEQyOFx1NTI5QlxcXFx6aXdpX3Byb2plY3RfU2FhU1xcXFxjb2RlXFxcXGZyb250ZW5kXCI7Y29uc3QgX192aXRlX2luamVjdGVkX29yaWdpbmFsX2ZpbGVuYW1lID0gXCJEOlxcXFxcdTVERTVcdTRFMUFcdTUxNDNcXFxcXHU2NTcwXHU0RTkxX1x1NjVCMFx1OEQyOFx1NTI5QlxcXFx6aXdpX3Byb2plY3RfU2FhU1xcXFxjb2RlXFxcXGZyb250ZW5kXFxcXHZpdGUuY29uZmlnLnRzXCI7Y29uc3QgX192aXRlX2luamVjdGVkX29yaWdpbmFsX2ltcG9ydF9tZXRhX3VybCA9IFwiZmlsZTovLy9EOi8lRTUlQjclQTUlRTQlQjglOUElRTUlODUlODMvJUU2JTk1JUIwJUU0JUJBJTkxXyVFNiU5NiVCMCVFOCVCNCVBOCVFNSU4QSU5Qi96aXdpX3Byb2plY3RfU2FhUy9jb2RlL2Zyb250ZW5kL3ZpdGUuY29uZmlnLnRzXCI7aW1wb3J0IHsgZGVmaW5lQ29uZmlnIH0gZnJvbSAndml0ZSdcbmltcG9ydCB2dWUgZnJvbSAnQHZpdGVqcy9wbHVnaW4tdnVlJ1xuaW1wb3J0IENvbXBvbmVudHMgZnJvbSAndW5wbHVnaW4tdnVlLWNvbXBvbmVudHMvdml0ZSdcbmltcG9ydCB7IFZhbnRSZXNvbHZlciB9IGZyb20gJ0B2YW50L2F1dG8taW1wb3J0LXJlc29sdmVyJ1xuXG5leHBvcnQgZGVmYXVsdCBkZWZpbmVDb25maWcoe1xuICBwbHVnaW5zOiBbXG4gICAgdnVlKCksXG4gICAgQ29tcG9uZW50cyh7XG4gICAgICByZXNvbHZlcnM6IFtWYW50UmVzb2x2ZXIoKV0sXG4gICAgfSksXG4gIF0sXG4gIHNlcnZlcjoge1xuICAgIHBvcnQ6IDUxNzMsXG4gICAgaG9zdDogJzAuMC4wLjAnLFxuICAgIHByb3h5OiB7XG4gICAgICAnL2FwaSc6IHtcbiAgICAgICAgdGFyZ2V0OiAnaHR0cDovL2xvY2FsaG9zdDo4MDAwJyxcbiAgICAgICAgY2hhbmdlT3JpZ2luOiB0cnVlLFxuICAgICAgfSxcbiAgICB9LFxuICB9LFxuICByZXNvbHZlOiB7XG4gICAgYWxpYXM6IHtcbiAgICAgICdAJzogJy9zcmMnLFxuICAgIH0sXG4gIH0sXG59KVxuIl0sCiAgIm1hcHBpbmdzIjogIjtBQUFxWSxTQUFTLG9CQUFvQjtBQUNsYSxPQUFPLFNBQVM7QUFDaEIsT0FBTyxnQkFBZ0I7QUFDdkIsU0FBUyxvQkFBb0I7QUFFN0IsSUFBTyxzQkFBUSxhQUFhO0FBQUEsRUFDMUIsU0FBUztBQUFBLElBQ1AsSUFBSTtBQUFBLElBQ0osV0FBVztBQUFBLE1BQ1QsV0FBVyxDQUFDLGFBQWEsQ0FBQztBQUFBLElBQzVCLENBQUM7QUFBQSxFQUNIO0FBQUEsRUFDQSxRQUFRO0FBQUEsSUFDTixNQUFNO0FBQUEsSUFDTixNQUFNO0FBQUEsSUFDTixPQUFPO0FBQUEsTUFDTCxRQUFRO0FBQUEsUUFDTixRQUFRO0FBQUEsUUFDUixjQUFjO0FBQUEsTUFDaEI7QUFBQSxJQUNGO0FBQUEsRUFDRjtBQUFBLEVBQ0EsU0FBUztBQUFBLElBQ1AsT0FBTztBQUFBLE1BQ0wsS0FBSztBQUFBLElBQ1A7QUFBQSxFQUNGO0FBQ0YsQ0FBQzsiLAogICJuYW1lcyI6IFtdCn0K
