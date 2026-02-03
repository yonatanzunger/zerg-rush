import { Bot, Shield, Layers, Zap } from 'lucide-react'
import Button from '../components/common/Button'
import { useAuth } from '../context/AuthContext'

const features = [
  {
    icon: Shield,
    title: 'Secure Isolation',
    description: 'Each agent runs in its own isolated VM with scoped credentials.',
  },
  {
    icon: Layers,
    title: 'Template Management',
    description: 'Save and restore agent states with templates and snapshots.',
  },
  {
    icon: Zap,
    title: 'Easy Control',
    description: 'Start, stop, and monitor your agent fleet from one dashboard.',
  },
]

export default function Landing() {
  const { login } = useAuth()

  return (
    <div className="min-h-screen bg-gradient-to-br from-primary-50 to-white">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Header */}
        <header className="py-6">
          <nav className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Bot className="h-8 w-8 text-primary-600" />
              <span className="text-xl font-bold text-gray-900">Zerg Rush</span>
            </div>
            <Button onClick={login}>Sign In</Button>
          </nav>
        </header>

        {/* Hero */}
        <main className="py-20 text-center">
          <h1 className="text-5xl font-bold text-gray-900 mb-6">
            Secure Agent Fleet Management
          </h1>
          <p className="text-xl text-gray-600 max-w-2xl mx-auto mb-10">
            Deploy, manage, and monitor AI agents securely. Each agent runs in
            complete isolation, protecting your environment from compromise.
          </p>
          <div className="flex items-center justify-center gap-4">
            <Button size="lg" onClick={login}>
              Get Started
            </Button>
            <Button size="lg" variant="secondary">
              Learn More
            </Button>
          </div>
        </main>

        {/* Features */}
        <section className="py-20">
          <div className="grid md:grid-cols-3 gap-8">
            {features.map((feature) => (
              <div
                key={feature.title}
                className="bg-white rounded-2xl p-8 shadow-sm border border-gray-100"
              >
                <div className="h-12 w-12 rounded-xl bg-primary-100 flex items-center justify-center mb-6">
                  <feature.icon className="h-6 w-6 text-primary-600" />
                </div>
                <h3 className="text-lg font-semibold text-gray-900 mb-2">
                  {feature.title}
                </h3>
                <p className="text-gray-600">{feature.description}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Footer */}
        <footer className="py-8 border-t border-gray-200">
          <p className="text-center text-gray-500 text-sm">
            &copy; 2024 Zerg Rush. Secure agent management.
          </p>
        </footer>
      </div>
    </div>
  )
}
