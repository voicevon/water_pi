$client = New-Object System.Net.Sockets.TcpClient
try {
    $client.Connect('192.168.121.119', 22)
    $stream = $client.GetStream()
    $stream.ReadTimeout = 5000
    $buffer = New-Object byte[] 1024
    $count = $stream.Read($buffer, 0, $buffer.Length)
    [System.Text.Encoding]::ASCII.GetString($buffer, 0, $count)
} catch {
    $_.Exception.Message
} finally {
    $client.Close()
}
