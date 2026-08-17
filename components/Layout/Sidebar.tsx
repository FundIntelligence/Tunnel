'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Brain, LayoutDashboard } from 'lucide-react';
import { motion } from 'framer-motion';

interface NavItem {
  name: string;
  href: string;
  icon: typeof LayoutDashboard;
}

const navigation: NavItem[] = [
  { name: 'Deal Analysis (v1)', href: '/v1/deal', icon: LayoutDashboard },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <div className="fixed left-0 top-0 h-full w-64 bg-base-900 border-r border-gray-800 flex flex-col z-50">
      {/* Logo Section */}
      <div className="p-6 border-b border-gray-800">
        <div className="flex items-center gap-3 mb-2">
          <div className="bg-gradient-to-br from-blue-500 to-cyan-400 p-2 rounded-lg">
            <Brain className="h-6 w-6 text-white" />
          </div>
          <h1 className="font-display text-2xl font-bold tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-cyan-300">
            Parity
          </h1>
        </div>
        <p className="text-xs text-gray-400">
          AI-Native Investment Intelligence
        </p>
        <div className="mt-2 inline-flex items-center px-2 py-1 rounded border border-teal/30 bg-teal/10">
            <div className="w-1.5 h-1.5 rounded-full bg-teal animate-pulse mr-2"></div>
            <span className="text-[10px] font-bold text-teal uppercase tracking-wider">Demo Mode</span>
        </div>
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
                    ? 'bg-base-900 border-l-2 border-accent-cyan text-accent-cyan shadow-glow-cyan' 
                    : 'text-gray-400 hover:bg-base-900 hover:shadow-glow-teal/50 hover:text-gray-200'
                  }
                `}
              >
                <Icon 
                  className={`h-5 w-5 transition-colors duration-200 ${
                    isActive 
                      ? 'text-accent-cyan' 
                      : 'text-gray-400 group-hover:text-gray-200'
                  }`} 
                />
                <span className="font-medium transition-colors duration-200">
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

