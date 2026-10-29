import { Component, ReactNode, ErrorInfo } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'

interface Props {
    children: ReactNode
}

interface State {
    hasError: boolean
    error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
    constructor(props: Props) {
        super(props)
        this.state = { hasError: false, error: null }
    }

    static getDerivedStateFromError(error: Error): State {
        return { hasError: true, error }
    }

    componentDidCatch(error: Error, errorInfo: ErrorInfo) {
        console.error('Uncaught error caught by ErrorBoundary:', error, errorInfo)
    }

    handleReload = () => {
        window.location.reload()
    }

    render() {
        if (this.state.hasError) {
            return (
                <div style={{ padding: '2rem', maxWidth: 650, margin: '3rem auto', textAlign: 'center' }}>
                    <div
                        style={{
                            background: 'var(--surface)',
                            border: '1px solid var(--border)',
                            borderRadius: 'var(--radius)',
                            padding: '2rem',
                            boxShadow: 'var(--shadow)',
                        }}
                    >
                        <div style={{ color: 'var(--danger)', marginBottom: '1rem', display: 'flex', justifyContent: 'center' }}>
                            <AlertTriangle size={48} />
                        </div>
                        <h2 style={{ fontSize: '1.3rem', marginBottom: '0.75rem', color: 'var(--text)' }}>
                            Something went wrong
                        </h2>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginBottom: '1.25rem', lineHeight: 1.5 }}>
                            The application encountered an unexpected error while rendering.
                        </p>
                        {this.state.error?.message && (
                            <pre
                                style={{
                                    background: '#070a12',
                                    border: '1px solid var(--border)',
                                    borderRadius: 'var(--radius-sm)',
                                    padding: '0.75rem',
                                    fontSize: '0.78rem',
                                    color: '#f87171',
                                    textAlign: 'left',
                                    overflowX: 'auto',
                                    marginBottom: '1.5rem',
                                    whiteSpace: 'pre-wrap',
                                }}
                            >
                                {this.state.error.message}
                            </pre>
                        )}
                        <button
                            type="button"
                            className="primary"
                            onClick={this.handleReload}
                            style={{ display: 'inline-flex', alignItems: 'center', gap: '0.45rem' }}
                        >
                            <RefreshCw size={15} /> Reload Dashboard
                        </button>
                    </div>
                </div>
            )
        }

        return this.props.children
    }
}
