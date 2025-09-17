// src/components/Header.tsx

import React from "react";
import { useAuth } from "../context/AuthContext";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "./ui/dropdown-menu";
import { Button } from "./ui/button";
import { ModeToggle } from "./ui/mode-toggle";
import { LogOut } from "lucide-react";

export default function Header() {
  const { user, logout } = useAuth();

  const displayName = user?.name || user?.email || "User";

  return (
    <header className="w-full flex items-center justify-between px-4 py-2 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700 shadow-sm">
      <h1 className="text-xl font-semibold select-none">
        byte
        <span className="tracking-tight font-bold text-indigo-600 dark:text-indigo-300">
          sophos
        </span>
      </h1>

      <div className="flex items-center gap-3">
        <ModeToggle />

        {user && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="flex items-center gap-2">
                <span className="font-medium">{displayName}</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-[150px]">
              <DropdownMenuItem
                onSelect={logout}
                className="flex items-center gap-2 text-red-600 dark:text-red-300 focus:text-red-600"
              >
                <LogOut className="h-4 w-4" />
                Logout
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
    </header>
  );
}
