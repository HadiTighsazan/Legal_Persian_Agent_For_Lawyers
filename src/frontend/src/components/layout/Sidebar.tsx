import { useLocation, useNavigate } from 'react-router-dom';
import { Activity, LayoutDashboard, FileText, MessageSquare, Search, Scale, X, Sparkles } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

interface NavItem {
  label: string;
  icon: React.ReactNode;
  href: string;
  disabled?: boolean;
}

const navItems: NavItem[] = [
  {
    label: 'Dashboard',
    icon: <LayoutDashboard className="h-5 w-5" />,
    href: '/dashboard',
  },
  {
    label: 'Documents',
    icon: <FileText className="h-5 w-5" />,
    href: '/documents',
  },
  {
    label: 'Legal Research',
    icon: <Search className="h-5 w-5" />,
    href: '/legal-research',
  },
  {
    label: 'Strategist',
    icon: <Scale className="h-5 w-5" />,
    href: '/strategist',
  },
  {
    label: 'Conversations',
    icon: <MessageSquare className="h-5 w-5" />,
    href: '/conversations',
    disabled: true,
  },
  {
    label: 'Monitoring',
    icon: <Activity className="h-5 w-5" />,
    href: '/monitoring',
  },
];

export default function Sidebar({ isOpen, onClose }: SidebarProps) {
  const location = useLocation();
  const navigate = useNavigate();

  const handleNavClick = (item: NavItem) => {
    if (item.disabled) return;
    navigate(item.href);
    onClose();
  };

  return (
    <>
      {/* Overlay backdrop — visible only on mobile when sidebar is open */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm lg:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          'fixed left-0 top-0 z-50 flex h-full w-64 flex-col border-r border-border/60 bg-background/95 backdrop-blur-sm transition-transform duration-200 ease-in-out',
          isOpen ? 'translate-x-0' : '-translate-x-full',
          'lg:translate-x-0'
        )}
      >
        {/* Brand / Logo */}
        <div className="flex h-16 items-center justify-between px-5">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
              <Sparkles className="h-4 w-4 text-primary" />
            </div>
            <span className="text-lg font-bold tracking-tight">DocuChat</span>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden hover:bg-muted/50"
            onClick={onClose}
            aria-label="Close sidebar"
          >
            <X className="h-5 w-5" />
          </Button>
        </div>

        <Separator className="bg-border/40" />

        {/* Navigation */}
        <nav className="flex-1 space-y-1 px-3 py-4">
          {navItems.map((item) => {
            const isActive =
              item.href === '/documents'
                ? location.pathname.startsWith('/documents')
                : item.href === '/legal-research'
                ? location.pathname.startsWith('/legal-research')
                : item.href === '/strategist'
                ? location.pathname.startsWith('/strategist')
                : location.pathname === item.href;

            return (
              <button
                key={item.href}
                onClick={() => handleNavClick(item)}
                disabled={item.disabled}
                className={cn(
                  'flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-150',
                  isActive && !item.disabled
                    ? 'bg-primary/8 text-primary shadow-sm'
                    : 'text-muted-foreground/80 hover:bg-muted/50 hover:text-foreground',
                  item.disabled && 'opacity-40 cursor-not-allowed'
                )}
              >
                <span className={cn(
                  'transition-colors',
                  isActive && !item.disabled ? 'text-primary' : 'text-muted-foreground/60'
                )}>
                  {item.icon}
                </span>
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>

        <Separator className="bg-border/40" />

        {/* Footer */}
        <div className="px-5 py-4">
          <p className="text-xs text-muted-foreground/50">
            &copy; {new Date().getFullYear()} DocuChat
          </p>
        </div>
      </aside>
    </>
  );
}
