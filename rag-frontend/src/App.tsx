// src/App.tsx

import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import AuthPage from "./pages/AuthPage";
import ChatPage from "./pages/ChatPage";
import Layout from "./components/Layout";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { ThemeProvider } from "./components/ui/theme-provider";

function AppRoutes() {
  const { token } = useAuth();

  return (
    <Routes>
      {!token ? (
        <Route path="/*" element={<AuthPage />} />
      ) : (
        <Route path="/" element={<Layout />}>
          <Route index element={<ChatPage />} />
          <Route path="conversation/:id" element={<ChatPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      )}
    </Routes>
  );
}

export default function App() {
  return (
    <ThemeProvider defaultTheme="system" storageKey="vite-ui-theme">
      <AuthProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
}
