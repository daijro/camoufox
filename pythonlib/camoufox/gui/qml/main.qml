import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: root
    visible: true
    width: 800
    height: 520
    minimumWidth: 640
    minimumHeight: 400
    title: "Camoufox Manager"
    color: c.bg

    FontLoader { id: segoe; source: "../assets/SegUIVar.ttf" }
    FontLoader { id: mdl2; source: "../assets/segmdl2.ttf" }

    // 4pt spacing scale
    property real scale: 1.0
    readonly property int row: Math.round(32 * scale)
    readonly property int s1: Math.round(4 * scale)
    readonly property int s2: Math.round(8 * scale)
    readonly property int s3: Math.round(12 * scale)
    readonly property int s4: Math.round(16 * scale)
    readonly property int textSm: Math.round(12 * scale)
    readonly property int textMd: Math.round(14 * scale)
    readonly property int colW: Math.round(100 * scale)
    readonly property string fontMain: segoe.name
    readonly property string fontIcon: mdl2.name

    property string geoipDlgSource: ""

    QtObject {
        id: c
        readonly property color bg: "#181818"
        readonly property color fg: "#1f1f1f"
        readonly property color raised: "#282828"
        readonly property color border: "#383838"
        readonly property color text: "#ffffff"
        readonly property color muted: "#a0a0a0"
        readonly property color dim: "#606060"
        readonly property color accent: "#569cd6"
        readonly property color ok: "#6b9e7e"
        readonly property color err: "#f14c4c"
    }

    // Primitives

    component T: Text {
        color: c.text
        font.family: fontMain
        font.pixelSize: textSm
    }

    component Muted: Text {
        color: c.muted
        font.family: fontMain
        font.pixelSize: textSm
    }

    component Bold: Text {
        color: c.text
        font.family: fontMain
        font.pixelSize: textSm
        font.weight: Font.DemiBold
    }

    component Header: Text {
        color: c.muted
        font.family: fontMain
        font.pixelSize: Math.round(10 * scale)
        font.weight: Font.DemiBold
        font.letterSpacing: 0.5
    }

    component Icon: Text {
        property string icon: ""
        text: icon
        color: c.text
        font.family: fontIcon
        font.pixelSize: textSm
    }

    component Rule: Rectangle {
        width: parent ? parent.width : 0
        height: 1
        color: c.border
    }

    component Btn: Rectangle {
        property string text: ""
        property string icon: ""
        property bool on: true
        property color accent: c.text
        signal clicked

        width: _row.implicitWidth + s3
        height: row - s2
        radius: s1
        color: on && _ma.containsMouse ? c.raised : "transparent"
        border.color: c.border
        border.width: 1
        opacity: on ? 1 : 0.4

        Row {
            id: _row
            anchors.centerIn: parent
            spacing: (icon && text) ? s1 : 0

            Icon {
                visible: !!icon
                anchors.verticalCenter: parent.verticalCenter
                icon: _row.parent.icon
                color: _row.parent.on ? _row.parent.accent : c.muted
            }

            T {
                visible: !!text
                anchors.verticalCenter: parent.verticalCenter
                text: _row.parent.text
                color: _row.parent.on ? _row.parent.accent : c.muted
            }
        }

        MouseArea {
            id: _ma
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: on ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: if (parent.on) parent.clicked()
        }
    }

    component Tag: Rectangle {
        property alias text: lbl.text
        property color accent: c.ok

        width: lbl.width + s3
        height: row - s3
        radius: s1
        color: Qt.rgba(accent.r, accent.g, accent.b, 0.15)
        border.color: accent
        border.width: 1

        T {
            id: lbl
            anchors.centerIn: parent
            color: parent.accent
            font.capitalization: Font.Capitalize
        }
    }

    component Check: Rectangle {
        property bool on: false

        width: s3
        height: s3
        radius: s1
        color: on ? c.accent : "transparent"
        border.color: on ? c.accent : c.muted
        border.width: 1

        Text {
            anchors.centerIn: parent
            text: "\uE73E"
            color: c.bg
            font.family: fontIcon
            font.pixelSize: Math.round(8 * scale)
            visible: parent.on
        }
    }

    component Input: Rectangle {
        property alias text: inp.text
        property alias input: inp
        property string placeholder: ""

        width: Math.round(160 * scale)
        height: row - s2
        radius: s1
        color: c.raised
        border.color: inp.activeFocus ? c.accent : c.border
        border.width: 1

        TextInput {
            id: inp
            anchors.fill: parent
            leftPadding: s2
            rightPadding: s2
            color: c.text
            font.family: fontMain
            font.pixelSize: textSm
            verticalAlignment: Text.AlignVCenter
        }

        Muted {
            anchors.left: parent.left
            anchors.leftMargin: s2
            anchors.verticalCenter: parent.verticalCenter
            text: placeholder
            visible: !inp.text && !inp.activeFocus
        }
    }

    component ProgressBar: Rectangle {
        id: _bar
        property real value: -1
        property bool active: false

        height: s1
        radius: s1 / 2
        color: c.raised

        Rectangle {
            id: _fill
            x: 0
            width: _bar.value >= 0 ? _bar.width * _bar.value : _bar.width * 0.3
            height: parent.height
            radius: parent.radius
            color: c.accent
        }

        Timer {
            interval: 16; repeat: true
            running: _bar.active && _bar.value < 0
            property real pos: 0
            property bool fwd: true
            onTriggered: {
                if (fwd) { pos += 0.02; if (pos >= 0.7) fwd = false }
                else { pos -= 0.02; if (pos <= 0) fwd = true }
                _fill.x = _bar.width * pos
            }
            onRunningChanged: if (!running) { pos = 0; _fill.x = 0 }
        }
    }

    component Combo: ComboBox {
        id: cb
        implicitWidth: colW
        implicitHeight: row - s2

        background: Rectangle {
            color: c.raised
            radius: s1
            border.color: c.border
            border.width: 1
        }

        contentItem: T {
            text: cb.displayText
            leftPadding: s2
            verticalAlignment: Text.AlignVCenter
        }

        delegate: ItemDelegate {
            required property int index
            required property string modelData
            width: cb.width
            height: row - s2
            contentItem: T {
                text: modelData
                verticalAlignment: Text.AlignVCenter
            }
            background: Rectangle {
                color: highlighted ? c.raised : c.fg
            }
        }
    }

    component SideRow: Rectangle {
        property bool sel: false
        property bool bar: false
        signal clicked

        width: parent ? parent.width : 0
        height: row
        color: sel ? c.raised : ma.containsMouse ? c.raised : "transparent"

        Rectangle {
            visible: bar && sel
            width: s1
            height: parent.height
            color: c.accent
        }

        MouseArea {
            id: ma
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: parent.clicked()
        }
    }

    component Panel: Rectangle {
        default property alias content: col.children
        property string title: ""

        color: c.bg

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            Rectangle {
                Layout.fillWidth: true
                height: row
                color: c.fg

                Rule { anchors.bottom: parent.bottom }

                Header {
                    anchors.left: parent.left
                    anchors.leftMargin: s3
                    anchors.verticalCenter: parent.verticalCenter
                    text: title
                }
            }

            ColumnLayout {
                id: col
                Layout.fillWidth: true
                Layout.margins: s4
                spacing: s3
            }

            Item { Layout.fillHeight: true }
        }
    }

    // Dialog

    property string dlgAct: ""
    property string dlgVer: ""
    property string dlgBuild: ""
    property int dlgIdx: -1

    function showDlg(act, idx, ver, build) {
        backend.selectVersion(idx)
        dlgAct = act
        dlgIdx = idx
        dlgVer = ver
        dlgBuild = build
    }

    Rectangle {
        anchors.fill: parent
        color: "#80000000"
        visible: dlgAct !== ""
        z: 100
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            onClicked: dlgAct = ""
        }
    }

    Rectangle {
        visible: dlgAct !== ""
        anchors.centerIn: parent
        width: Math.round(340 * scale)
        height: dlgContent.height + s4 * 2
        color: c.fg
        border.color: c.border
        radius: s2
        z: 101

        Column {
            id: dlgContent
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: s4
            spacing: s3

            Bold {
                text: (dlgAct === "install" || dlgAct === "promptInstall") ? "Install"
                     : dlgAct === "uninstall" ? "Uninstall" : "Set Active"
                font.pixelSize: textMd
            }

            T {
                width: parent.width
                wrapMode: Text.Wrap
                text: dlgAct === "promptInstall"
                    ? "Camoufox " + dlgVer + "-" + dlgBuild + " is now active but not installed. Install it now?"
                    : (dlgAct === "install" ? "Install" : dlgAct === "uninstall" ? "Remove" : "Set") +
                      " Camoufox " + dlgVer + "-" + dlgBuild +
                      (dlgAct === "install" ? "?" : dlgAct === "uninstall" ? " from disk?" : " as active?")
            }

            T {
                visible: (dlgAct === "install" || dlgAct === "promptInstall") && backend.selectedIsPrerelease
                width: parent.width
                color: c.err
                wrapMode: Text.Wrap
                text: "Warning: Prerelease versions may be unstable."
            }

            Item { width: 1; height: s1 }

            Row {
                anchors.right: parent.right
                spacing: s2

                Btn {
                    text: dlgAct === "promptInstall" ? "Skip" : "Cancel"
                    onClicked: dlgAct = ""
                }

                Btn {
                    text: (dlgAct === "install" || dlgAct === "promptInstall") ? "Install"
                        : dlgAct === "uninstall" ? "Uninstall" : "Set Active"
                    accent: dlgAct === "uninstall" ? c.err
                        : (dlgAct === "install" || dlgAct === "promptInstall") ? c.ok : c.accent
                    onClicked: {
                        if (dlgAct === "install" || dlgAct === "promptInstall") {
                            backend.installSelected()
                        } else if (dlgAct === "uninstall") {
                            backend.uninstallSelected()
                        } else if (dlgAct === "channel") {
                            backend.confirmFollowChannel()
                            if (backend.canInstall) {
                                dlgAct = "promptInstall"
                                return
                            }
                        } else {
                            backend.setActive(dlgIdx)
                            backend.selectVersion(dlgIdx)
                            if (backend.canInstall) {
                                dlgAct = "promptInstall"
                                return
                            }
                        }
                        dlgAct = ""
                    }
                }
            }
        }
    }

    Connections {
        target: backend
        function onCurrentRepoChanged() {
            repoList.currentIndex = backend.currentRepoIndex
        }
        function onChannelPrompt(idx, display, build) {
            showDlg("channel", idx, display, build)
        }
    }

    // Layout

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // Tab bar
        Rectangle {
            Layout.fillWidth: true
            height: row
            color: c.fg

            Rule { anchors.bottom: parent.bottom }

            Row {
                anchors.left: parent.left
                anchors.leftMargin: s3
                anchors.verticalCenter: parent.verticalCenter

                Repeater {
                    model: ["Browsers", "GeoIP", "Info"]

                    Rectangle {
                        width: tabLbl.width + s4 * 2
                        height: row
                        color: "transparent"

                        T {
                            id: tabLbl
                            anchors.centerIn: parent
                            text: modelData
                            color: tabs.currentIndex === index ? c.accent : c.muted
                        }

                        Rectangle {
                            anchors.bottom: parent.bottom
                            width: parent.width
                            height: s1 / 2
                            color: c.accent
                            visible: tabs.currentIndex === index
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: tabs.currentIndex = index
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // Sidebar
            Rectangle {
                Layout.preferredWidth: Math.round(210 * scale)
                Layout.fillHeight: true
                color: c.fg
                visible: tabs.currentIndex === 0

                Rectangle {
                    anchors.right: parent.right
                    width: 1
                    height: parent.height
                    color: c.border
                }

                Column {
                    anchors.top: parent.top
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.rightMargin: 1

                    Rectangle {
                        width: parent.width
                        height: row
                        color: "transparent"

                        Header {
                            anchors.left: parent.left
                            anchors.leftMargin: s3
                            anchors.verticalCenter: parent.verticalCenter
                            text: "REPOSITORIES"
                        }
                    }

                    ListView {
                        id: repoList
                        width: parent.width
                        height: contentHeight
                        interactive: false
                        model: backend.repos

                        delegate: SideRow {
                            sel: ListView.isCurrentItem
                            bar: true

                            T {
                                anchors.left: parent.left
                                anchors.leftMargin: s4
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData
                            }

                            onClicked: {
                                repoList.currentIndex = index
                                backend.selectRepo(index)
                            }
                        }

                        Component.onCompleted: backend.selectRepo(0)
                    }

                    Rule {}

                    Rectangle {
                        width: parent.width
                        height: row
                        color: "transparent"

                        Header {
                            anchors.left: parent.left
                            anchors.leftMargin: s3
                            anchors.verticalCenter: parent.verticalCenter
                            text: "FOLLOW CHANNEL"
                        }
                    }

                    Repeater {
                        model: backend.channels

                        Rectangle {
                            width: parent ? parent.width : 0
                            height: row + s2
                            color: chMa.containsMouse ? c.raised : "transparent"

                            Column {
                                anchors.left: parent.left
                                anchors.leftMargin: s4
                                anchors.right: parent.right
                                anchors.rightMargin: s3
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 1

                                Row {
                                    spacing: s2
                                    Check { on: backend.followedChannel === backend.channelKeys[index]; anchors.verticalCenter: parent.verticalCenter }
                                    T { text: (backend.followedChannel === backend.channelKeys[index] ? "Following " : "Follow ") + modelData; anchors.verticalCenter: parent.verticalCenter }
                                }

                                Muted {
                                    leftPadding: s3 + s2
                                    text: backend.channelLatest[index] ? ("Latest: " + backend.channelLatest[index]) : "(sync first)"
                                    font.pixelSize: Math.round(10 * scale)
                                }
                            }

                            MouseArea {
                                id: chMa
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: backend.setFollowedChannel(index)
                            }
                        }
                    }
                }

            }

            StackLayout {
                id: tabs
                Layout.fillWidth: true
                Layout.fillHeight: true

                // Browsers
                Rectangle {
                    color: c.bg

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        Rectangle {
                            Layout.fillWidth: true
                            height: row
                            color: c.fg

                            Rule { anchors.bottom: parent.bottom }

                            Row {
                                anchors.left: parent.left
                                anchors.leftMargin: s3
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: s3

                                Rectangle {
                                    width: s3
                                    height: s3
                                    radius: s1
                                    color: "transparent"
                                    border.color: c.dim
                                    border.width: 1
                                    anchors.verticalCenter: parent.verticalCenter
                                }

                                Header {
                                    text: "VERSION"
                                    width: colW
                                    anchors.verticalCenter: parent.verticalCenter
                                }

                                Header {
                                    text: "BUILD"
                                    width: colW
                                    anchors.verticalCenter: parent.verticalCenter
                                }

                                Header {
                                    text: "STATUS"
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }
                        }

                        ListView {
                            id: vList
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            model: backend.versionModel

                            property real scrollBarWidth: vScrollBar.visible ? vScrollBar.width : 0

                            ScrollBar.vertical: ScrollBar {
                                id: vScrollBar
                                policy: vList.contentHeight > vList.height ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff
                                contentItem: Rectangle {
                                    implicitWidth: s2
                                    radius: s1
                                    color: c.border
                                }
                            }

                            delegate: Rectangle {
                                id: vrow
                                property bool hov: hover.hovered

                                width: vList.width - vList.scrollBarWidth
                                height: row
                                color: model.isHeader ? c.fg :
                                       model.isPinned ? Qt.rgba(c.accent.r, c.accent.g, c.accent.b, 0.06) :
                                       hov ? Qt.rgba(1, 1, 1, 0.02) : "transparent"

                                Rectangle {
                                    anchors.top: parent.top
                                    width: parent.width
                                    height: 1
                                    color: model.isHeader && index > 0 ? c.border : "transparent"
                                }

                                Rectangle {
                                    anchors.bottom: parent.bottom
                                    width: parent.width
                                    height: 1
                                    color: model.isHeader ? c.border : "transparent"
                                }

                                Rectangle {
                                    width: s1
                                    height: parent.height
                                    color: model.isPinned && !model.isHeader ? c.accent : "transparent"
                                }

                                HoverHandler { id: hover }

                                Bold {
                                    anchors.left: parent.left
                                    anchors.leftMargin: s3
                                    anchors.verticalCenter: parent.verticalCenter
                                    visible: model.isHeader
                                    text: model.display
                                }

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: s3
                                    anchors.rightMargin: s2
                                    spacing: s3
                                    visible: !model.isHeader

                                    Check {
                                        on: model.isPinned
                                        MouseArea {
                                            anchors.fill: parent
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: showDlg("setActive", index, model.display, model.build)
                                        }
                                    }

                                    T {
                                        text: model.display
                                        color: model.isInstalled ? c.text : c.dim
                                        Layout.preferredWidth: colW
                                    }

                                    Muted {
                                        text: model.build
                                        Layout.preferredWidth: colW
                                    }

                                    Row {
                                        spacing: s2
                                        Layout.fillWidth: true

                                        Tag {
                                            visible: model.isInstalled
                                            text: "installed"
                                        }

                                        Tag {
                                            visible: model.isActive
                                            text: "active"
                                            accent: c.accent
                                        }
                                    }

                                    Btn {
                                        visible: vrow.hov && !model.isInstalled
                                        icon: "\uE896"
                                        text: "Download"
                                        accent: c.ok
                                        on: !backend.busy
                                        onClicked: showDlg("install", index, model.display, model.build)
                                    }

                                    Btn {
                                        visible: vrow.hov && model.isInstalled
                                        icon: "\uE74D"
                                        text: "Delete"
                                        accent: c.err
                                        on: !backend.busy
                                        onClicked: showDlg("uninstall", index, model.display, model.build)
                                    }
                                }
                            }
                        }

                    }
                }

                // GeoIP
                Rectangle {
                    color: c.bg

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 0

                        Rectangle {
                            Layout.fillWidth: true
                            height: row
                            color: c.fg

                            Rule { anchors.bottom: parent.bottom }

                            Header {
                                anchors.left: parent.left
                                anchors.leftMargin: s3
                                anchors.verticalCenter: parent.verticalCenter
                                text: "GEOIP DATABASE"
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            visible: !backend.geoipAvailable
                            height: visible ? notInstalledCol.height + s4 * 2 : 0
                            color: c.fg

                            ColumnLayout {
                                id: notInstalledCol
                                anchors.centerIn: parent
                                spacing: s2

                                T {
                                    Layout.alignment: Qt.AlignHCenter
                                    text: "IP Geolocation support is missing."
                                    font.pixelSize: textMd
                                }

                                T {
                                    Layout.alignment: Qt.AlignHCenter
                                    text: "Run: pip install camoufox[geoip]"
                                    color: c.muted
                                    font.family: root.fontMain
                                }
                            }
                        }

                        Column {
                            Layout.fillWidth: true
                            visible: backend.geoipAvailable
                            spacing: 0

                            Repeater {
                                model: backend.geoipSources

                                Rectangle {
                                    id: geoRow
                                    property bool hov: geoHover.hovered
                                    property bool active: backend.geoipInstalled === modelData
                                    property bool downloaded: backend.geoipDownloaded.indexOf(modelData) >= 0

                                    width: parent.width
                                    height: row
                                    color: active ? Qt.rgba(c.accent.r, c.accent.g, c.accent.b, 0.06) :
                                           hov ? Qt.rgba(1, 1, 1, 0.02) : "transparent"

                                    Rectangle {
                                        width: s1
                                        height: parent.height
                                        color: geoRow.active ? c.accent : "transparent"
                                    }

                                    HoverHandler { id: geoHover }

                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            if (backend.geoipBusy) return
                                            if (!geoRow.downloaded) {
                                                root.geoipDlgSource = modelData
                                            } else if (!geoRow.active) {
                                                backend.setActiveGeoip(modelData)
                                            }
                                        }
                                    }

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: s3
                                        anchors.rightMargin: s3
                                        spacing: s3

                                        T {
                                            text: modelData
                                            color: geoRow.downloaded ? c.text : c.dim
                                            Layout.fillWidth: true
                                        }

                                        Tag {
                                            visible: geoRow.active
                                            text: "active"
                                            accent: c.accent
                                        }

                                        Btn {
                                            visible: geoRow.hov && !geoRow.downloaded
                                            icon: "\uE896"
                                            text: "Download"
                                            accent: c.ok
                                            on: !backend.geoipBusy
                                            onClicked: root.geoipDlgSource = modelData
                                        }

                                        Btn {
                                            visible: geoRow.hov && geoRow.downloaded && !geoRow.active
                                            icon: "\uE74D"
                                            text: "Delete"
                                            accent: c.err
                                            on: !backend.geoipBusy
                                            onClicked: backend.deleteGeoipSource(modelData)
                                        }
                                    }
                                }
                            }
                        }

                        Rule { Layout.fillWidth: true; Layout.topMargin: s3; visible: backend.geoipAvailable }

                        // IP Lookup
                        ColumnLayout {
                            visible: backend.geoipAvailable
                            Layout.fillWidth: true
                            Layout.margins: s4
                            spacing: s2

                            Bold { text: "IP Lookup" }

                            Row {
                                spacing: s2

                                Input {
                                    id: ipIn
                                    placeholder: "Enter IP..."
                                    input.onAccepted: backend.lookupIp(text)
                                }

                                Btn {
                                    text: "Lookup"
                                    onClicked: backend.lookupIp(ipIn.text)
                                }
                            }

                            T {
                                visible: backend.lookupResult.length > 0
                                text: backend.lookupResult
                                textFormat: Text.RichText
                                color: backend.lookupSuccess ? c.ok : c.err
                            }
                        }

                        Item { Layout.fillHeight: true }

                        Rectangle {
                            Layout.fillWidth: true
                            visible: backend.geoipInstalled.length > 0 || backend.geoipBusy
                            height: visible ? metaCol.height + s4 * 2 : 0
                            color: c.fg

                            Rule { anchors.top: parent.top }

                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: s4
                                spacing: s4

                                Column {
                                    id: metaCol
                                    Layout.fillWidth: true
                                    spacing: s1

                                    Row {
                                        spacing: s2
                                        Muted { text: "Path:" }
                                        T { text: backend.geoipPath }
                                    }

                                    Row {
                                        spacing: s2
                                        Muted { text: "Size:" }
                                        T { text: backend.geoipSize }
                                    }

                                    Row {
                                        spacing: s2
                                        Muted { text: "Downloaded:" }
                                        T { text: backend.geoipMtime }
                                    }
                                }

                                Btn {
                                    icon: "\uE72C"
                                    accent: c.accent
                                    on: !backend.geoipBusy && backend.geoipInstalled.length > 0
                                    onClicked: backend.refreshGeoip()
                                }

                                Btn {
                                    icon: "\uE838"
                                    accent: c.text
                                    on: backend.geoipInstalled.length > 0
                                    onClicked: backend.openGeoipFolder()
                                }

                                Btn {
                                    icon: "\uE74D"
                                    accent: c.err
                                    on: !backend.geoipBusy && backend.geoipInstalled.length > 0
                                    onClicked: backend.deleteGeoipData()
                                }
                            }
                        }

                        ProgressBar {
                            Layout.fillWidth: true
                            visible: backend.geoipBusy
                            height: s2
                            radius: 0
                            value: backend.geoipProgress
                            active: backend.geoipBusy
                        }
                    }

                    // GeoIP download dialog
                    Rectangle {
                        anchors.fill: parent
                        color: "#80000000"
                        visible: root.geoipDlgSource !== ""
                        z: 100

                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: root.geoipDlgSource = ""
                        }
                    }

                    Rectangle {
                        visible: root.geoipDlgSource !== ""
                        anchors.centerIn: parent
                        width: Math.round(320 * scale)
                        height: Math.round(140 * scale)
                        color: c.fg
                        border.color: c.border
                        radius: s2
                        z: 101

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: s4
                            spacing: s3

                            Bold {
                                text: "Download GeoIP Database"
                                font.pixelSize: textMd
                            }

                            T {
                                Layout.fillWidth: true
                                wrapMode: Text.Wrap
                                text: "Download " + root.geoipDlgSource + " database? This will download both IPv4 and IPv6 files."
                            }

                            Item { Layout.fillHeight: true }

                            Row {
                                Layout.alignment: Qt.AlignRight
                                spacing: s2

                                Btn {
                                    text: "Cancel"
                                    onClicked: root.geoipDlgSource = ""
                                }

                                Btn {
                                    text: "Download"
                                    accent: c.ok
                                    onClicked: {
                                        backend.downloadGeoip(root.geoipDlgSource)
                                        root.geoipDlgSource = ""
                                    }
                                }
                            }
                        }
                    }
                }

                // Info
                Panel {
                    title: "SYSTEM INFO"

                    GridLayout {
                        columns: 2
                        columnSpacing: s4 * 2
                        rowSpacing: s2

                        Muted { text: backend.activeBrowserLabel }
                        Bold { text: backend.activeBrowserText; color: backend.activeBrowserColor }

                        Muted { text: "Python Library" }
                        T { text: backend.libraryVersion }

                        Muted { text: "Playwright" }
                        T { text: backend.playwrightVersion }

                        Muted { text: "Browserforge" }
                        T { text: backend.browserforgeVersion }

                        Muted { text: "Fingerprints" }
                        T { text: backend.fingerprintVersion }

                        Muted { text: "Last Sync" }
                        T { text: backend.lastSyncTime || "Never" }

                        Muted { text: "Website" }
                        T {
                            text: "<a href='https://camoufox.com' style='color:" + c.accent + "'>camoufox.com</a>"
                            textFormat: Text.RichText
                            onLinkActivated: link => Qt.openUrlExternally(link)
                        }
                    }

                    Rule { visible: debugMode }

                    Bold { text: "Debug Options"; visible: debugMode }

                    Row {
                        visible: debugMode
                        spacing: s4

                        Row {
                            spacing: s2
                            Muted { text: "Spoof OS"; anchors.verticalCenter: parent.verticalCenter }
                            Combo {
                                model: backend.spoofOsOptions
                                currentIndex: backend.spoofOsIndex
                                onActivated: backend.setSpoofOs(currentIndex)
                                implicitWidth: Math.round(90 * scale)
                            }
                        }

                        Row {
                            spacing: s2
                            Muted { text: "Spoof Arch"; anchors.verticalCenter: parent.verticalCenter }
                            Combo {
                                model: backend.spoofArchOptions
                                currentIndex: backend.spoofArchIndex
                                onActivated: backend.setSpoofArch(currentIndex)
                                implicitWidth: Math.round(90 * scale)
                            }
                        }

                        Row {
                            spacing: s2
                            Muted { text: "Lib Version"; anchors.verticalCenter: parent.verticalCenter }
                            Rectangle {
                                width: Math.round(80 * scale)
                                height: Math.round(24 * scale)
                                color: "#1affffff"
                                radius: Math.round(3 * scale)
                                TextInput {
                                    anchors.fill: parent
                                    anchors.margins: Math.round(4 * scale)
                                    color: "#fff"
                                    font.pixelSize: Math.round(11 * scale)
                                    text: backend.spoofLibVer
                                    verticalAlignment: TextInput.AlignVCenter
                                    clip: true
                                    selectByMouse: true
                                    property string placeholder: "(auto)"
                                    Text {
                                        text: parent.placeholder
                                        color: "#80ffffff"
                                        font: parent.font
                                        visible: !parent.text && !parent.activeFocus
                                        anchors.verticalCenter: parent.verticalCenter
                                    }
                                    onEditingFinished: backend.setSpoofLibVer(text)
                                }
                            }
                        }
                    }


                    Rule { visible: debugMode }

                    Row {
                        visible: debugMode
                        spacing: s3

                        Muted { text: "UI Scale"; anchors.verticalCenter: parent.verticalCenter }

                        Slider {
                            id: scaleSlider
                            from: 0.8
                            to: 1.5
                            stepSize: 0.1
                            value: root.scale
                            onPressedChanged: if (!pressed) root.scale = value
                            implicitWidth: Math.round(140 * scale)
                            implicitHeight: row - s2

                            background: Rectangle {
                                x: scaleSlider.leftPadding
                                y: scaleSlider.topPadding + scaleSlider.availableHeight / 2 - s1 / 2
                                width: scaleSlider.availableWidth
                                height: s1
                                radius: s1 / 2
                                color: c.raised

                                Rectangle {
                                    width: scaleSlider.visualPosition * parent.width
                                    height: s1
                                    radius: s1 / 2
                                    color: c.accent
                                }
                            }

                            handle: Rectangle {
                                x: scaleSlider.leftPadding + scaleSlider.visualPosition * (scaleSlider.availableWidth - width)
                                y: scaleSlider.topPadding + scaleSlider.availableHeight / 2 - height / 2
                                width: s4
                                height: s4
                                radius: s2
                                color: scaleSlider.pressed ? c.accent : c.text
                            }
                        }

                        T { text: Math.round(scaleSlider.value * 100) + "%" }
                    }
                }
            }
        }

        // Status bar
        Rectangle {
            visible: tabs.currentIndex === 0
            Layout.fillWidth: true
            height: row
            color: c.fg

            Rule { anchors.top: parent.top }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: s3
                anchors.rightMargin: s3
                spacing: s2

                Btn {
                    visible: debugMode
                    text: "Refresh"
                    on: !backend.busy
                    onClicked: backend.refresh()
                }

                Btn {
                    icon: "\uE895"
                    text: "Sync Repos"
                    accent: c.accent
                    on: !backend.busy
                    onClicked: backend.sync()
                }

                Muted {
                    text: backend.lastSyncTime ? "Synced: " + backend.lastSyncTime : "Sync has not been ran yet."
                    visible: !backend.busy
                }

                Item { Layout.fillWidth: true }

                T {
                    visible: backend.statusText.length > 0
                    text: backend.statusText
                    color: backend.statusColor
                    Layout.maximumWidth: Math.round(200 * scale)
                    elide: Text.ElideRight
                }

                Row {
                    visible: backend.busy
                    spacing: s2

                    ProgressBar {
                        width: Math.round(80 * scale)
                        value: backend.progress
                        active: backend.busy
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    Btn {
                        text: "Cancel"
                        accent: c.err
                        onClicked: backend.cancelOperation()
                    }
                }

                T {
                    visible: backend.activeLabel.length > 0
                    text: backend.activeLabel
                    color: c.accent
                    Layout.maximumWidth: Math.round(200 * scale)
                    elide: Text.ElideRight
                }
            }
        }
    }
}
