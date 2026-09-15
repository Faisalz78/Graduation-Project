import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const variants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-teal-600 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-[#0b5d3f] text-white hover:bg-[#074832] shadow-sm",
        outline: "border border-[#d9cfbd] bg-[#fffdf8] text-[#294437] hover:bg-[#f4ecdf]",
        ghost: "text-[#62716b] hover:bg-[#efe6d8] hover:text-[#153f30]",
      },
      size: { default: "h-12 px-5 text-sm", sm: "h-10 px-4 text-sm", icon: "h-11 w-11" },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);
type Props = React.ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof variants> & { asChild?: boolean };
export function Button({ className, variant, size, asChild = false, ...props }: Props) {
  const Component = asChild ? Slot : "button";
  return <Component className={cn(variants({ variant, size, className }))} {...props} />;
}
