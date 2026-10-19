// Workaround that accesses Playwright's `launchServer` method in Python
// Without having to install the Node.js Playwright library.

const path = require('path')

// The driver shipped with playwright-python is a copy of playwright-core, so its
// entrypoint exposes `launchServer`. Resolve through the entrypoint rather than lib/
// internals, whose layout is private and changes between releases: 1.60 bundled
// lib/browserServerImpl.js away, which broke this script.
const driverPackage = process.argv[2]

let playwright
try {
    playwright = require(path.join(driverPackage, 'index.js'))
} catch (error) {
    console.error(`Error loading the Playwright driver from ${driverPackage}:`, error.message)
    process.exit(1)
}

process.stdin.setEncoding('utf8')

// Attach lifecycle listeners before reading configuration so an early terminal
// event cannot arrive between setup and browser launch. Resolve with a possible
// stream error instead of rejecting early, which would otherwise become an
// unhandled rejection while configuration is still being collected.
const stdinTerminated = new Promise((resolve) => {
    let settled = false
    const cleanup = () => {
        process.stdin.removeListener('end', onEnd)
        process.stdin.removeListener('close', onClose)
        process.stdin.removeListener('error', onError)
    }
    const finish = (error = null) => {
        if (settled)
            return
        settled = true
        cleanup()
        resolve(error)
    }
    const onEnd = () => finish()
    const onClose = () => finish()
    const onError = (error) => finish(error)

    process.stdin.once('end', onEnd)
    process.stdin.once('close', onClose)
    process.stdin.once('error', onError)
})

function parseOptions(data) {
    return JSON.parse(Buffer.from(data, 'base64').toString())
}

function collectData() {
    return new Promise((resolve, reject) => {
        let data = ''
        let settled = false

        const cleanup = () => {
            process.stdin.removeListener('data', onData)
            process.stdin.removeListener('end', onEnd)
            process.stdin.removeListener('close', onClose)
            process.stdin.removeListener('error', onError)
        }
        const finish = (encoded) => {
            if (settled)
                return
            settled = true
            cleanup()
            try {
                resolve(parseOptions(encoded))
            } catch (error) {
                reject(error)
            }
        }
        const onData = (chunk) => {
            data += chunk
            const newline = data.indexOf('\n')
            if (newline !== -1)
                finish(data.slice(0, newline))
        }
        // Accept the old EOF-delimited format as a fallback for direct callers.
        const onEnd = () => finish(data)
        const onClose = () => finish(data)
        const onError = (error) => {
            if (settled)
                return
            settled = true
            cleanup()
            reject(error)
        }

        process.stdin.on('data', onData)
        process.stdin.once('end', onEnd)
        process.stdin.once('close', onClose)
        process.stdin.once('error', onError)
        process.stdin.resume()
    })
}

async function main() {
    const options = await collectData()

    console.time('Server launched')
    console.info('Launching server...')
    const browserServer = await playwright.firefox.launchServer(options)
    console.timeEnd('Server launched')
    console.log('Websocket endpoint:\x1b[93m', browserServer.wsEndpoint(), '\x1b[0m')

    const stdinError = await stdinTerminated
    await browserServer.close()
    if (stdinError)
        throw stdinError
}

main().catch((error) => {
    console.error('Error launching server:', error.message)
    process.exit(1)
})
