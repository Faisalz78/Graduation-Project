import * as React from "react";
import { cn } from "@/lib/utils";
export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn("form-field", className)} {...props} />;
}
