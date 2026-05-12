import { useLocation, useNavigate } from 'react-router-dom';
import { Activity, LayoutDashboard, FileText, MessageSquare, Search, X } from 'lucide-react';
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
    // disabled: true,  // removed — Documents nav is now active
  },
  {
    label: 'Legal Research',
    icon: <Search className="h-5 w-5" />,
    href: '/legal-research',
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
          className="fixed inset-0 z-40 bg-black/50 lg:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          'fixed left-0 top-0 z-50 flex h-full w-64 flex-col border-r bg-background transition-transform duration-200 ease-in-out',
          isOpen ? 'translate-x-0' : '-translate-x-full',
          'lg:translate-x-0'
        )}
      >
        {/* Brand / Logo */}
        <div className="flex h-16 items-center justify-between px-6">
          <span className="text-xl font-bold tracking-tight">DocuChat</span>
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            onClick={onClose}
            aria-label="Close sidebar"
          >
            <X className="h-5 w-5" />
          </Button>
        </div>

        <Separator />

        {/* Navigation */}
        <nav className="flex-1 space-y-1 px-3 py-4">
          {navItems.map((item) => {
            const isActive =
              item.href === '/documents'
                ? location.pathname.startsWith('/documents')
                : item.href === '/legal-research'
                ? location.pathname.startsWith('/legal-research')
                : location.pathname === item.href;

            return (
              <button
                key={item.href}
                onClick={() => handleNavClick(item)}
                disabled={item.disabled}
                className={cn(
                  'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                  isActive && !item.disabled
                    ? 'bg-accent text-accent-foreground'
                    : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
                  item.disabled && 'opacity-50 cursor-not-allowed'
                )}
              >
                {item.icon}
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>

        <Separator />

        {/* Footer */}
        <div className="px-6 py-4">
          <p className="text-xs text-muted-foreground">
            &copy; {new Date().getFullYear()} DocuChat
          </p>
        </div>
      </aside>
    </>
  );
}
