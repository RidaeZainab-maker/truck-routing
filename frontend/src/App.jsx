import { useEffect, useState } from 'react'
import { Box, Button, Chip, Paper, Stack, TextField, Typography } from '@mui/material'
import { MapContainer, TileLayer } from 'react-leaflet'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default function App() {
  const [status, setStatus] = useState('checking...')
  const [form, setForm] = useState({ origin: '', destination: '', departure: '', loadWeight: '' })

  useEffect(() => {
    fetch(`${API}/api/health`)
      .then((r) => r.json())
      .then((d) => setStatus(d.status))
      .catch(() => setStatus('offline'))
  }, [])

  const update = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  const handleSubmit = (e) => {
    e.preventDefault()
    // TODO: POST form to `${API}/api/routes`, store the result in state,
    // draw routes/checkpoints on the map, show the recommendation.
    console.log('submit', form)
  }

  return (
    <Box sx={{ display: 'flex', height: '100vh' }}>
      <Paper component="form" onSubmit={handleSubmit} sx={{ width: 360, p: 3, overflowY: 'auto' }} square>
        <Stack spacing={2}>
          <Typography variant="h5">Truck Route Planner</Typography>
          <Chip
            label={`Backend: ${status}`}
            color={status === 'ok' ? 'success' : status === 'offline' ? 'error' : 'default'}
          />
          <TextField label="Origin" value={form.origin} onChange={update('origin')} required />
          <TextField label="Destination" value={form.destination} onChange={update('destination')} required />
          <TextField
            label="Departure"
            type="datetime-local"
            value={form.departure}
            onChange={update('departure')}
            slotProps={{ inputLabel: { shrink: true } }}
            required
          />
          <TextField label="Load weight (lb)" type="number" value={form.loadWeight} onChange={update('loadWeight')} required />
          <Button type="submit" variant="contained">Plan routes</Button>
          {/* TODO: route list + risk summary + recommendation */}
          {/* TODO (Day 4): 0-48h forecast slider for the heatmap */}
        </Stack>
      </Paper>
      <Box sx={{ flex: 1 }}>
        <MapContainer center={[39.5, -98.35]} zoom={4} style={{ height: '100%', width: '100%' }}>
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {/* TODO: <Polyline> per route, <CircleMarker> per checkpoint colored by risk */}
        </MapContainer>
      </Box>
    </Box>
  )
}
