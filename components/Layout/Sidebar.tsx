'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { 
  FolderOpen, 
  Bot, 
  BarChart3, 
  Settings,
  Brain
} from 'lucide-react';
import { motion } from 'framer-motion';

interface NavItem {
  name: string;
  href: string;
  icon: typeof FolderOpen;
}

const navigation: NavItem[] = [
  { name: 'Connect Data', href: '/connect-data', icon: FolderOpen },
  { name: 'Companion', href: '/companion', icon: Bot },
  { name: 'Reports', href: '/reports', icon: BarChart3 },
  { name: 'Rules & Settings', href: '/rules', icon: Settings },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <div className="fixed left-0 top-0 h-full w-64 bg-[#0D0F12] border-r border-gray-800 flex flex-col z-50">
      {/* Logo Section */}
      <div className="p-6 border-b border-gray-800">
        <div className="flex items-center gap-3 mb-2">
          <div className="bg-gradient-to-br from-cyan-400 to-green-400 p-2 rounded-lg">
            <Brain className="h-6 w-6 text-[#0D0F12]" />
          </div>
          <h1 className="text-xl font-bold text-white">FundIQ</h1>
        </div>
        <p className="text-xs text-gray-400">
          Make better investments
        </p>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-2">
        {navigation.map((item, index) => {
          const isActive = pathname === item.href;
          const Icon = item.icon;

          return (
            <Link key={item.name} href={item.href}>
              <motion.div
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.2, delay: index * 0.1 }}
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
                className={`
                  flex items-center gap-3 px-4 py-3 rounded-lg transition-all duration-200
                  ${isActive 
                    ? 'bg-gradient-to-r from-cyan-400/20 to-green-400/20 border-l-2 border-cyan-400 shadow-[0_0_15px_rgba(34,211,238,0.3)]' 
                    : 'hover:bg-[#23272E]'
                  }
                `}
              >
                <Icon 
                  className={`h-5 w-5 transition-colors duration-200 ${
                    isActive 
                      ? 'text-cyan-400' 
                      : 'text-gray-400'
                  }`} 
                />
                <span 
                  className={`font-medium transition-colors duration-200 ${
                    isActive 
                      ? 'text-white bg-gradient-to-r from-cyan-400 to-green-400 bg-clip-text text-transparent' 
                      : 'text-gray-300'
                  }`}
                >
                  {item.name}
                </span>
              </motion.div>
            </Link>
          );
        })}
      </nav>
    </div>
  );
}

