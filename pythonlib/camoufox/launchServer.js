// Workaround that accesses Playwright's undocumented `launchServer` method in Python
// Without having to use the Node.js Playwright library.

const { BrowserServerLauncherImpl } = require(`${process.cwd()}/lib/browserServerImpl.js`)

function collectData() {
    return new Promise((resolve) => {
        let data = '';
        process.stdin.setEncoding('utf8');

        process.stdin.on('data', (chunk) => {
            data += chunk;
        });

        process.stdin.on('end', () => {
            resolve(JSON.parse(data));
        });
    });
}

collectData().then((options) => {
    console.time('Server launched');
    console.info('Launching server...');
    
    const server = new BrowserServerLauncherImpl('firefox')
    
    // Call Playwright's `launchServer` method
    server.launchServer(options).then(browserServer => {
        console.timeEnd('Server launched');
        console.log('Websocket endpoint:\x1b[93m', browserServer.wsEndpoint(), '\x1b[0m');
        // Continue forever
        process.stdin.resume();
    }).catch(error => {
        console.error('Error launching server:', error.message);
        process.exit(1);
    });
}).catch((error) => {
    console.error('Error collecting data:', error.message);
    process.exit(1);  // Exit with error code
});